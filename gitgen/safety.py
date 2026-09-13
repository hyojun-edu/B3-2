"""Sensitive data masking and diff size limiting."""

import re
from typing import Optional


def mask_secrets(text: str, extra_patterns: Optional[list] = None) -> str:
    patterns = [
        (r"(?i)(authorization:\s*bearer\s+)[^\s]+", r"\1[REDACTED]"),
        (r"(?i)(api[_-]?key\s*[=:]\s*)[^\s,;]+", r"\1[REDACTED]"),
        (r"(?i)(secret|token|password|passwd)\s*[=:]\s*[^\s,;]+", r"\1=[REDACTED]"),
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


def limit_diff(text: str, max_files: int = 10, max_lines: int = 200) -> tuple[str, int]:
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
    return "\n".join(output), count
