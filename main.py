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
    "language": "영어",
    "commit": {
        "prefixes": ["feat", "fix", "docs", "refactor", "test", "chore"],
        "scope": True,
        "max_title_length": 72,
        "body_bullets": 3,
    },
    "pr": {
        "tone": "간결하고 사실 중심",
        "title_prefix": False,
        "sections": ["Why", "What"],
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
        if key.strip() in ("sections", "mask_patterns"):
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
        # 대소문자를 구분하지 않고 `authorization:` 뒤의 공백과 `bearer` 토큰을
        # 캡처한다. 토큰 값은 공백이 나올 때까지(`[^\s]+`) 포함하며, 치환 시
        # 첫 번째 캡처 그룹(헤더 부분)은 보존하고 인증값만 `[REDACTED]`로 바꾼다.
        (r"(?i)(authorization:\s*bearer\s+)[^\s]+", r"\1[REDACTED]"),
        # `api_key`, `api-key`, `apikey`처럼 밑줄/하이픈이 있거나 없는 API 키
        # 이름을 찾는다. `=` 또는 `:` 앞뒤의 선택적 공백까지 헤더로 캡처하고,
        # 쉼표·세미콜론·공백 전까지를 키 값으로 보아 값만 마스킹한다.
        (r"(?i)(api[_-]?key\s*[=:]\s*)[^\s,;]+", r"\1[REDACTED]"),
        # `secret`, `token`, `password`, `passwd` 중 하나가 키 이름으로 나오고
        # `=` 또는 `:` 뒤에 값이 이어지는 형태를 찾는다. 키 이름과 구분자 앞의
        # 부분을 캡처해 두지만, 현재 치환식은 캡처 그룹 1(키 이름) 뒤를
        # 고정 문자열로 대체하므로 원문의 구분자/공백은 보존하지 않는다.
        (r"(?i)(secret|token|password|passwd)\s*[=:]\s*[^\s,;]+", r"\1=[REDACTED]"),
        # 이메일의 로컬 파트(`+`, `.`, `-`, 영숫자 등)와 `@` 뒤의 도메인을
        # 찾는다. 도메인은 하나 이상의 `.` 구간을 요구하므로 `a@b.c`는
        # 매칭하지만 `a@b`는 매칭하지 않으며, 주소 전체를 마스킹한다.
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
            # 설정 파일/CLI에서 전달된 동적 정규식은 실제 치환 전에 컴파일해
            # 문법 오류를 조기에 확인한다. 이 값은 고정 리터럴이 아니므로
            # 사용자가 원하는 추가 마스킹 규칙을 그대로 지원한다.
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
    # 문자열 맨 앞의 Markdown 코드 펜스(`````, 선택적인 text/markdown 언어명,
    # 뒤따르는 공백) 또는 맨 끝의 닫는 펜스를 제거한다. `|`로 두 경우를
    # 나누고 `re.I`로 언어명 대소문자를 무시해 모델 응답을 일반 텍스트로 정리한다.
    text = re.sub(r"^```(?:text|markdown)?\s*|\s*```$", "", text.strip(), flags=re.I)
    return text.strip()


def commit_prompt(status: str, diff: str, convention: dict) -> str:
    rules = convention["commit"]
    prefixes = ", ".join(rules["prefixes"])
    scope = "Use a scope in parentheses when useful." if rules["scope"] else "Do not use a scope."
    return f"""Create a commit message from this Git change. Output only the message: a single title line (maximum {rules['max_title_length']} characters), optionally followed by a blank line and up to {rules['body_bullets']} bullet lines. Write in {convention['language']}. Use one of these exact prefixes with the configured capitalization: {prefixes}. {scope} Keep the message concise and factual.\n\nGit status:\n{status}\n\nGit diff:\n{diff}"""


def pr_prompt(status: str, diff: str, convention: dict) -> str:
    rules = convention["pr"]
    commit_rules = convention["commit"]
    sections = rules["sections"]
    section_format = "\n\n".join(f"## {name}\n- ..." for name in sections)
    if rules["title_prefix"]:
        prefixes = ", ".join(commit_rules["prefixes"])
        prefix_rule = f"Use one of these exact title prefixes with the configured capitalization: {prefixes}."
    else:
        prefix_rule = "Do not force a prefix in the title."
    return f"""Create a pull request draft from this Git change. Use a {rules['tone']} tone. Write the title and all section content in {convention['language']}. Output exactly this Markdown structure, with at least one bullet under every section:
Title: <one-line title, maximum 80 characters>

{section_format}
{prefix_rule} Do not add unconfigured sections. Use the actual change and sensible test commands.

Git status:
{status}

Git diff:
{diff}"""


def normalize_commit(text: str, convention: dict) -> str:
    lines = [line.strip() for line in clean_text(text).splitlines() if line.strip()]
    if not lines:
        return "변경 사항 요약"
    title = lines[0].lstrip("- ")[: convention["commit"]["max_title_length"]]
    bullets = [line if line.startswith("-") else f"- {line}" for line in lines[1 : 1 + convention["commit"]["body_bullets"]]]
    return "\n".join([title, *bullets])


def normalize_pr(text: str, convention: dict) -> str:
    text = clean_text(text)
    # 줄의 시작(`^`)에 있는 `Title:`을 대소문자 구분 없이 찾고, 콜론 뒤의
    # 공백을 건너뛴 뒤 그 줄의 제목 내용(`.+`)을 캡처한다. `re.M`은 여러 줄
    # 문자열에서 각 줄을 시작점으로 취급하고, `re.I`는 `title:`도 허용한다.
    title_match = re.search(r"(?im)^title:\s*(.+)$", text)
    title = (title_match.group(1).strip() if title_match else "변경 사항 반영")[:80]
    sections = {}
    section_names = convention["pr"]["sections"]
    for name in section_names:
        # 설정된 섹션 이름을 Markdown 헤더(`##`)에서 찾는다. 헤더 안의
        # 선택적 공백을 허용하고, 해당 헤더 다음 줄부터 다음 `##` 헤더 또는
        # 문자열 끝(`\Z`) 직전까지를 비탐욕적으로 캡처한다. `re.M`은 헤더를
        # 줄 단위로 찾게 하고, `re.S`는 섹션 내용의 줄바꿈도 `.`에 포함한다.
        match = re.search(
            rf"(?ms)^##\s*{re.escape(name)}\s*\n(.*?)(?=^##\s|\Z)",
            text,
        )
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
