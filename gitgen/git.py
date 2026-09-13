"""Git repository and diff handling."""

import os
import subprocess
from pathlib import Path
from typing import Optional

from .errors import GitError
from .safety import limit_diff, mask_secrets


def run_git(*args: str) -> str:
    try:
        result = subprocess.run(["git", *args], text=True, capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "").strip()
        raise GitError(detail or "Git 명령을 실행할 수 없습니다.") from exc
    return result.stdout


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
        diff = run_git("diff") + run_git("diff", "--cached")
    untracked = []
    for line in status.splitlines():
        # `git diff`에는 아직 추적되지 않은 파일이 포함되지 않으므로,
        # status의 `?? ` 항목을 찾아 파일 내용을 AI 입력용 diff에 추가한다.
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
        diff, line_count = limit_diff(diff, max_files=safe_config.get("max_files", 10), max_lines=safe_config.get("max_lines", 200))
    else:
        line_count = len(diff.splitlines())
    return status, diff, line_count
