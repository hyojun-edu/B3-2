#!/usr/bin/env python3
"""Generate commit messages and pull request drafts from the current Git diff."""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_ENDPOINT = "https://copa.codyssey.kr/v1/chat/completions"
DEFAULT_MODEL = "gpt-5.4-mini"


class GitError(RuntimeError):
    pass


def run_git(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args], text=True, capture_output=True, check=True
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "").strip()
        raise GitError(detail or "Git 명령을 실행할 수 없습니다.") from exc
    return result.stdout


def git_context(safe_mode: bool) -> tuple[str, str, int]:
    try:
        root = Path(run_git("rev-parse", "--show-toplevel").strip())
    except GitError as exc:
        raise GitError("Git이 초기화된 프로젝트 루트에서 실행해 주세요.") from exc
    os.chdir(root)

    status = run_git("status", "--short").strip()
    if not status:
        return "", "", 0

    try:
        diff = run_git("diff", "HEAD")
    except GitError:
        # An initial repository has no HEAD yet. Collect staged and unstaged
        # tracked changes separately in that case.
        diff = run_git("diff") + run_git("diff", "--cached")
    # git diff does not include untracked files; include their text as context.
    untracked = []
    for line in status.splitlines():
        if line.startswith("?? "):
            relative = line[3:]
            path = Path(relative)
            if path.is_file():
                try:
                    untracked.append(f"--- new file: {relative} ---\n{path.read_text(errors='replace')}")
                except OSError:
                    pass
    if untracked:
        diff += "\n" + "\n".join(untracked)

    if safe_mode:
        diff = mask_secrets(diff)
        diff = limit_diff(diff)
    return status, diff, len(diff.splitlines())


def mask_secrets(text: str) -> str:
    patterns = [
        (r"(?i)(authorization:\s*bearer\s+)[^\s]+", r"\1[REDACTED]"),
        (r"(?i)(api[_-]?key\s*[=:]\s*)[^\s,;]+", r"\1[REDACTED]"),
        (r"(?i)(secret|token|password|passwd)\s*[=:]\s*[^\s,;]+", r"\1=[REDACTED]"),
        (r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "[REDACTED_EMAIL]"),
    ]
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text)
    return text


def limit_diff(text: str, max_files: int = 10, max_lines: int = 200) -> str:
    lines = text.splitlines()
    output, files, count = [], 0, 0
    for line in lines:
        if line.startswith("diff --git ") or line.startswith("--- new file: "):
            files += 1
            if files > max_files:
                break
        if count >= max_lines:
            break
        output.append(line)
        count += 1
    if len(lines) > len(output):
        output.append("[safe-mode: diff가 파일 10개/200줄로 제한되었습니다]")
    return "\n".join(output)


def call_api(prompt: str, args: argparse.Namespace) -> str:
    key = os.getenv("AI_API_KEY")
    if not key:
        raise RuntimeError("AI_API_KEY 환경변수가 설정되지 않았습니다. 예: export AI_API_KEY=\"YOUR_KEY\"")
    payload = {
        "model": args.model,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "messages": [{"role": "system", "content": "You generate precise Git text. Follow the requested format exactly."},
                     {"role": "user", "content": prompt}],
    }
    request = urllib.request.Request(
        args.endpoint,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            body = json.loads(response.read().decode())
        return body["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:500]
        raise RuntimeError(f"AI API 요청 실패 (HTTP {exc.code}): {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"AI API 네트워크 오류: {exc}") from exc
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"AI API 응답 형식이 올바르지 않습니다: {exc}") from exc


def clean_text(text: str) -> str:
    text = re.sub(r"^```(?:text|markdown)?\s*|\s*```$", "", text.strip(), flags=re.I)
    return text.strip()


def commit_prompt(status: str, diff: str) -> str:
    return f"""Create a commit message from this Git change. Output only the message: a single title line (maximum 72 characters), optionally followed by a blank line and 1-3 bullet lines. Mention concrete files or modules when useful. Use a conventional prefix such as feat, fix, refactor, or docs.\n\nGit status:\n{status}\n\nGit diff:\n{diff}"""


def pr_prompt(status: str, diff: str) -> str:
    return f"""Create a pull request draft from this Git change. Output exactly this Markdown structure, with at least one bullet under every section:\nTitle: <one-line title, maximum 80 characters>\n\n## Why\n- ...\n\n## What\n- ...\n\n## How to Test\n- ...\nDo not add any other sections. Use the actual change and sensible test commands.\n\nGit status:\n{status}\n\nGit diff:\n{diff}"""


def normalize_commit(text: str) -> str:
    lines = [line.strip() for line in clean_text(text).splitlines() if line.strip()]
    if not lines:
        return "변경 사항 요약"
    title = lines[0].lstrip("- ")[:72]
    bullets = [line if line.startswith("-") else f"- {line}" for line in lines[1:4]]
    return "\n".join([title, *bullets])


def normalize_pr(text: str) -> str:
    text = clean_text(text)
    title_match = re.search(r"(?im)^title:\s*(.+)$", text)
    title = (title_match.group(1).strip() if title_match else "변경 사항 반영")[:80]
    sections = {}
    for name in ("Why", "What", "How to Test"):
        match = re.search(rf"(?ms)^##\s*{re.escape(name)}\s*\n(.*?)(?=^##\s|\Z)", text)
        content = match.group(1).strip() if match else "- 변경 사항을 확인합니다."
        bullets = [line.strip() for line in content.splitlines() if line.strip().startswith("-")]
        sections[name] = "\n".join(bullets or ["- 변경 사항을 확인합니다."])
    return f"Title: {title}\n\n" + "\n\n".join(f"## {name}\n{sections[name]}" for name in sections)


def main() -> int:
    parser = argparse.ArgumentParser(description="Git diff 기반 커밋 메시지/PR 초안 생성기")
    parser.add_argument("command", choices=("commit", "pr"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=600)
    parser.add_argument("--endpoint", default=os.getenv("OPENAI_API_ENDPOINT", DEFAULT_ENDPOINT))
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--safe-mode", action="store_true", help="민감정보 마스킹 및 diff 전송량 제한")
    args = parser.parse_args()
    try:
        status, diff, line_count = git_context(args.safe_mode)
        if not status:
            print("[INFO] 변경 사항이 없습니다. 생성을 종료합니다.")
            return 0
        print(f"[INFO] Git status 수집 완료: {len(status.splitlines())}개 항목")
        print(status)
        print(f"[INFO] Git diff 수집 완료: {line_count}줄")
        print("[INFO] AI API 요청 중... (1회)")
        result = call_api(commit_prompt(status, diff) if args.command == "commit" else pr_prompt(status, diff), args)
        print("[DONE] 생성 완료")
        print("\n--- Commit Message ---" if args.command == "commit" else "\n--- PR Draft ---")
        print(normalize_commit(result) if args.command == "commit" else normalize_pr(result))
        print("----------------------")
        return 0
    except (GitError, RuntimeError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
