"""Convention and CLI configuration handling."""

import json
from pathlib import Path
from typing import Optional, Tuple

DEFAULT_ENDPOINT = "https://copa.codyssey.kr/v1/chat/completions"
DEFAULT_MODEL = "gpt-5.4-mini"
DEFAULT_CONVENTION_FILE = ".ai-gitgen.yml"

DEFAULT_CONVENTION = {
    "language": "영어",
    "commit": {"prefixes": ["feat", "fix", "docs", "refactor", "test", "chore"], "scope": True, "max_title_length": 72, "body_bullets": 3},
    "pr": {"tone": "간결하고 사실 중심", "title_prefix": False, "sections": ["Why", "What"]},
    "safe_mode": {"max_files": 10, "max_lines": 200, "mask_patterns": []},
}

LIST_KEYS = {"prefixes", "sections", "mask_patterns"}


def _scalar(value: str):
    """설정 파일의 문자열 값을 bool, int, list 등의 Python 값으로 변환한다.

    YAML 라이브러리 없이도 이 프로젝트에서 사용하는 간단한 설정 형식을
    읽을 수 있도록, 설정값의 실제 타입을 복원하기 위해 필요하다.
    """
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


def _merge_dict(base: dict, override: dict) -> None:
    """사용자 설정을 기본 설정에 재귀적으로 합친다.

    설정 파일에 일부 항목만 작성해도 나머지 기본값을 유지할 수 있도록,
    중첩된 딕셔너리는 안쪽까지 합치고 나머지 값만 덮어쓴다.
    """
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge_dict(base[key], value)
        else:
            base[key] = value


def _parse_line(raw_line: str) -> Optional[Tuple[int, str]]:
    """주석과 빈 줄을 제거하고 들여쓰기와 실제 내용을 반환한다."""
    line = raw_line.split("#", 1)[0].rstrip()
    if not line.strip():
        return None
    indent = len(line) - len(line.lstrip())
    return indent, line.strip()


def _parent_for_indent(stack: list[tuple[int, dict]], indent: int) -> dict:
    """중첩 설정의 들여쓰기 스택을 조정하고 현재 부모 딕셔너리를 반환한다."""
    while stack[-1][0] >= indent:
        stack.pop()
    return stack[-1][1]


def _parse_convention_file(config_path: Path) -> dict:
    """컨벤션 파일에서 이 프로젝트가 지원하는 간단한 YAML 형식을 파싱한다."""
    parsed = {}
    stack = [(-1, parsed)]
    pending_list = None

    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        parsed_line = _parse_line(raw_line)
        # 빈 줄이나 주석만 있는 줄은 설정에 영향을 주지 않으므로 건너뛴다.
        if parsed_line is None:
            continue

        indent, content = parsed_line
        # `- value` 형식의 줄은 바로 앞에서 시작한 리스트에 항목으로 추가한다.
        if content.startswith("- "):
            if pending_list is not None:
                pending_list.append(_scalar(content[2:]))
            continue
        # 매핑 항목은 반드시 `key: value` 또는 `key:` 형식이어야 한다.
        if ":" not in content:
            raise ValueError(f"컨벤션 설정 형식이 올바르지 않습니다: {raw_line.strip()}")

        key, value = (part.strip() for part in content.split(":", 1))
        parent = _parent_for_indent(stack, indent)

        # `key: value`처럼 값이 같은 줄에 있으면 타입을 변환해 바로 저장한다.
        if value:
            parent[key] = _scalar(value)
            pending_list = None
        else:
            # `key:`처럼 값이 없으면, 리스트 키는 새 리스트로 시작하고
            # 그 외의 키는 다음 들여쓰기 항목을 담을 중첩 딕셔너리로 시작한다.
            parent[key] = [] if key in LIST_KEYS else {}
            pending_list = parent[key] if key in LIST_KEYS else None
            if isinstance(parent[key], dict):
                stack.append((indent, parent[key]))

    return parsed


def load_convention(path: str) -> dict:
    convention = json.loads(json.dumps(DEFAULT_CONVENTION))
    config_path = Path(path)
    if not config_path.is_file():
        return convention

    parsed = _parse_convention_file(config_path)
    _merge_dict(convention, parsed)
    return convention


def build_safe_config(args, convention: dict) -> dict:
    config = dict(convention.get("safe_mode", {}))
    if args.safe_max_files is not None:
        config["max_files"] = args.safe_max_files
    if args.safe_max_lines is not None:
        config["max_lines"] = args.safe_max_lines
    if args.safe_mask_regex:
        config["mask_patterns"] = list(config.get("mask_patterns", [])) + args.safe_mask_regex
    return config
