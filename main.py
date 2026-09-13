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
from typing import Optional


DEFAULT_ENDPOINT = "https://copa.codyssey.kr/v1/chat/completions"
DEFAULT_MODEL = "gpt-5.4-mini"
DEFAULT_CONVENTION_FILE = ".ai-gitgen.yml"

DEFAULT_CONVENTION = {
    "commit": {
        "prefixes": ["Feat", "Fix", "Docs", "Refactor", "Test", "Chore"],
        "scope": False,
        "language": "한국어",
        "max_title_length": 72,
        "body_bullets": 3,
    },
    "pr": {
        "tone": "간결하고 사실 중심",
        "title_prefix": True,
        "sections": ["Why", "What", "How to Test"],
        "checklist": [],
    },
    "safe_mode": {
        "max_files": 10,
        "max_lines": 200,
        # Each item uses the form: regular-expression => replacement.
        "mask_patterns": [],
    },
}


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


def _scalar(value: str):
    """Parse the small YAML subset used by .ai-gitgen.yml without dependencies."""
    value = value.strip()
    if not value:
        return {}
    if value.startswith("[") and value.endswith("]"):
        return [_scalar(item) for item in value[1:-1].split(",") if item.strip()]
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    try:
        return int(value)
    except ValueError:
        return value


def load_convention(path: str) -> dict:
    """Load a YAML convention file, accepting the common scalar/list subset."""
    convention = json.loads(json.dumps(DEFAULT_CONVENTION))
    config_path = Path(path)
    if not config_path.is_file():
        return convention

    parsed = {}
    stack = [(-1, parsed)]
    pending_list = None
    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        content = line.strip()
        if content.startswith("- "):
            if pending_list is not None:
                pending_list.append(_scalar(content[2:]))
            continue
        if ":" not in content:
            raise ValueError(f"컨벤션 설정 형식이 올바르지 않습니다: {raw_line.strip()}")
        key, value = content.split(":", 1)
        while stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        if value.strip():
            parent[key.strip()] = _scalar(value)
            pending_list = None
        else:
            parent[key.strip()] = {}
            stack.append((indent, parent[key.strip()]))
            pending_list = None
        if key.strip() in ("sections", "checklist", "mask_patterns"):
            parent[key.strip()] = []
            pending_list = parent[key.strip()]
    _merge_dict(convention, parsed)
    return convention


def _merge_dict(base: dict, override: dict) -> None:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge_dict(base[key], value)
        else:
            base[key] = value


def git_context(safe_mode: bool, safe_config: Optional[dict] = None) -> tuple[str, str, int]:
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
        safe_config = safe_config or {}
        diff = mask_secrets(diff, safe_config.get("mask_patterns", []))
        diff = limit_diff(
            diff,
            max_files=safe_config.get("max_files", 10),
            max_lines=safe_config.get("max_lines", 200),
        )
    return status, diff, len(diff.splitlines())


def mask_secrets(text: str, extra_patterns: Optional[list] = None) -> str:
    patterns = [
        # (?i)는 대소문자를 구분하지 않게 하며, `authorization:` 뒤의 공백과
        # `bearer` 인증 방식을 `( ... )` 그룹으로 보존한다. 그 뒤의 `[^\s]+`는
        # 공백이 나올 때까지의 토큰값을 선택하므로, 전체 인증값을 마스킹한다.
        (r"(?i)(authorization:\s*bearer\s+)[^\s]+", r"\1[REDACTED]"),
        # API 키 표기를 대소문자 구분 없이 찾는다. `api[_-]?key`는 `apikey`,
        # `api_key`, `api-key`를 모두 허용하고, `\s*[=:]\s*`는 `=` 또는 `:`
        # 앞뒤 공백을 허용한다. 이후 `[^\s,;]+`가 공백·쉼표·세미콜론 전까지의
        # 실제 키 값을 골라 앞부분 그룹(`\1`)은 남긴 채 치환한다.
        (r"(?i)(api[_-]?key\s*[=:]\s*)[^\s,;]+", r"\1[REDACTED]"),
        # `secret`, `token`, `password`, `passwd` 중 하나를 찾고, 뒤의 `\s*[=:]\s*`
        # 로 키-값 구분자와 공백을 허용한다. 값은 공백·쉼표·세미콜론이 나오기
        # 전까지 매칭된다. 이름과 구분자까지를 그룹으로 보존하고 값만 대체한다.
        (r"(?i)(secret|token|password|passwd)\s*[=:]\s*[^\s,;]+", r"\1=[REDACTED]"),
        # 이메일의 로컬 파트(`[\w.+-]+`)와 `@` 뒤의 호스트를 찾는다.
        # 호스트는 `\w` 또는 하이픈으로 된 라벨 하나 이상과 점으로 구분된
        # 도메인 라벨을 요구하므로, `user@example.com` 같은 주소 전체가 선택된다.
        (r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "[REDACTED_EMAIL]"),
    ]
    for item in extra_patterns or []:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            pattern, replacement = item
        elif isinstance(item, str) and "=>" in item:
            pattern, replacement = item.split("=>", 1)
        else:
            raise ValueError("safe_mode.mask_patterns는 '정규식=>치환값' 형식이어야 합니다.")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"safe mode 마스킹 정규식이 올바르지 않습니다: {pattern}: {exc}") from exc
        patterns.append((pattern, replacement))
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text)
    return text


def limit_diff(text: str, max_files: int = 10, max_lines: int = 200) -> str:
    if max_files < 0 or max_lines < 0:
        raise ValueError("safe mode의 max_files/max_lines는 0 이상이어야 합니다.")
    lines = text.splitlines()
    output, files, count = [], 0, 0
    truncated = False
    for line in lines:
        if line.startswith("diff --git ") or line.startswith("--- new file: "):
            files += 1
            if files > max_files:
                truncated = True
                break
        if count >= max_lines:
            truncated = True
            break
        output.append(line)
        count += 1
    if truncated:
        output.append(f"[safe-mode: diff가 파일 {max_files}개/{max_lines}줄로 제한되었습니다]")
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
    # 문자열 처음의 Markdown 코드 펜스(`````, 선택적인 `text`/`markdown`, 공백)나
    # 문자열 끝의 닫는 펜스(````)를 제거한다. `|`는 두 경우 중 하나를 뜻하고,
    # `(?:...)`는 치환에 필요 없는 비캡처 그룹이며, `re.I`로 언어 이름의 대소문자를
    # 구분하지 않는다. `^`/`$`와 `text.strip()`으로 양 끝의 펜스만 처리한다.
    text = re.sub(r"^```(?:text|markdown)?\s*|\s*```$", "", text.strip(), flags=re.I)
    return text.strip()


def commit_prompt(status: str, diff: str, convention: dict) -> str:
    rules = convention["commit"]
    prefixes = ", ".join(rules["prefixes"])
    scope = "Use a scope in parentheses when useful." if rules["scope"] else "Do not use a scope."
    return f"""Create a commit message from this Git change. Output only the message: a single title line (maximum {rules['max_title_length']} characters), optionally followed by a blank line and up to {rules['body_bullets']} bullet lines. Write in {rules['language']}. Use one of these exact prefixes with the configured capitalization: {prefixes}. {scope} Keep the message concise and factual.\n\nGit status:\n{status}\n\nGit diff:\n{diff}"""


def pr_prompt(status: str, diff: str, convention: dict) -> str:
    rules = convention["pr"]
    sections = rules["sections"]
    section_format = "\n\n".join(f"## {name}\n- ..." for name in sections)
    checklist = ""
    if rules["checklist"]:
        checklist = "\n\nChecklist:\n" + "\n".join(f"- [ ] {item}" for item in rules["checklist"])
    prefix_rule = "Use the configured commit-style prefix in the title." if rules["title_prefix"] else "Do not force a prefix in the title."
    return f"""Create a pull request draft from this Git change. Use a {rules['tone']} tone. Output exactly this Markdown structure, with at least one bullet under every section:\nTitle: <one-line title, maximum 80 characters>\n\n{section_format}{checklist}\n{prefix_rule} Do not add unconfigured sections. Use the actual change and sensible test commands.\n\nGit status:\n{status}\n\nGit diff:\n{diff}"""


def normalize_commit(text: str, convention: dict) -> str:
    lines = [line.strip() for line in clean_text(text).splitlines() if line.strip()]
    if not lines:
        return "변경 사항 요약"
    title = lines[0].lstrip("- ")[: convention["commit"]["max_title_length"]]
    bullets = [line if line.startswith("-") else f"- {line}" for line in lines[1 : 1 + convention["commit"]["body_bullets"]]]
    return "\n".join([title, *bullets])


def normalize_pr(text: str, convention: dict) -> str:
    text = clean_text(text)
    # `re.M`(`m`)로 각 줄을 시작점으로 취급하고 `re.I`(`i`)로 `Title:`의
    # 대소문자를 무시한다. 줄 시작의 `title:` 뒤 공백을 건너뛴 다음, 해당 줄의
    # 나머지 한 글자 이상(`.+`)을 캡처해 PR 제목으로 사용한다. `$`는 제목이
    # 여러 줄로 번지지 않도록 줄 끝을 지정한다.
    title_match = re.search(r"(?im)^title:\s*(.+)$", text)
    title = (title_match.group(1).strip() if title_match else "변경 사항 반영")[:80]
    sections = {}
    section_names = convention["pr"]["sections"]
    for name in section_names:
        # `re.M`로 `^`가 모든 줄의 시작을 가리키게 하고, `re.S`로 `.`이 줄바꿈도
        # 포함하도록 한다. `^##\s*`는 Markdown 2단계 헤더를 찾고, `re.escape(name)`은
        # 설정값을 정규식 문법이 아닌 글자 그대로 비교하게 한다. 헤더 뒤 줄바꿈부터
        # 다음 `##` 헤더 또는 문자열 끝(`\Z`) 직전까지를 최소 반복(`.*?`)으로 캡처한다.
        # 따라서 현재 섹션의 내용만 `group(1)`으로 얻을 수 있다.
        match = re.search(rf"(?ms)^##\s*{re.escape(name)}\s*\n(.*?)(?=^##\s|\Z)", text)
        content = match.group(1).strip() if match else "- 변경 사항을 확인합니다."
        bullets = [line.strip() for line in content.splitlines() if line.strip().startswith("-")]
        sections[name] = "\n".join(bullets or ["- 변경 사항을 확인합니다."])
    checklist = ""
    if convention["pr"]["checklist"]:
        checklist = "\n\nChecklist:\n" + "\n".join(f"- [ ] {item}" for item in convention["pr"]["checklist"])
    return f"Title: {title}\n\n" + "\n\n".join(f"## {name}\n{sections[name]}" for name in sections) + checklist


def main() -> int:
    parser = argparse.ArgumentParser(description="Git diff 기반 커밋 메시지/PR 초안 생성기")
    parser.add_argument("command", choices=("commit", "pr"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=600)
    parser.add_argument("--endpoint", default=os.getenv("OPENAI_API_ENDPOINT", DEFAULT_ENDPOINT))
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--safe-mode", action="store_true", help="민감정보 마스킹 및 diff 전송량 제한")
    parser.add_argument(
        "--safe-max-files",
        type=int,
        help="safe mode에서 전송할 최대 파일 수 (기본값: 10)",
    )
    parser.add_argument(
        "--safe-max-lines",
        type=int,
        help="safe mode에서 전송할 최대 diff 줄 수 (기본값: 200)",
    )
    parser.add_argument(
        "--safe-mask-regex",
        action="append",
        default=[],
        metavar="REGEX=>REPLACEMENT",
        help="safe mode에 추가할 마스킹 규칙. 여러 번 지정 가능",
    )
    parser.add_argument("--convention", default=DEFAULT_CONVENTION_FILE, help="커밋/PR 컨벤션 YAML 파일 경로")
    args = parser.parse_args()
    try:
        convention = load_convention(args.convention)
        safe_config = dict(convention.get("safe_mode", {}))
        if args.safe_max_files is not None:
            safe_config["max_files"] = args.safe_max_files
        if args.safe_max_lines is not None:
            safe_config["max_lines"] = args.safe_max_lines
        if args.safe_mask_regex:
            safe_config["mask_patterns"] = list(safe_config.get("mask_patterns", [])) + args.safe_mask_regex
        status, diff, line_count = git_context(args.safe_mode, safe_config)
        if not status:
            print("[INFO] 변경 사항이 없습니다. 생성을 종료합니다.")
            return 0
        print(f"[INFO] Git status 수집 완료: {len(status.splitlines())}개 항목")
        print(status)
        print(f"[INFO] Git diff 수집 완료: {line_count}줄")
        print("[INFO] AI API 요청 중... (1회)")
        prompt = commit_prompt(status, diff, convention) if args.command == "commit" else pr_prompt(status, diff, convention)
        result = call_api(prompt, args)
        print("[DONE] 생성 완료")
        print("\n--- Commit Message ---" if args.command == "commit" else "\n--- PR Draft ---")
        print(normalize_commit(result, convention) if args.command == "commit" else normalize_pr(result, convention))
        print("----------------------")
        return 0
    except (GitError, RuntimeError, ValueError, TypeError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
