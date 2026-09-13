#!/usr/bin/env python3
"""Generate commit messages and pull request drafts from the current Git diff."""

import argparse
import os
import sys

from gitgen.ai import call_api
from gitgen.config import DEFAULT_CONVENTION_FILE, DEFAULT_ENDPOINT, DEFAULT_MODEL, build_safe_config, load_convention
from gitgen.errors import APP_ERRORS
from gitgen.git import git_context
from gitgen.normalize import normalize_result
from gitgen.prompts import build_prompt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Git diff 기반 커밋 메시지/PR 초안 생성기")
    parser.add_argument("command", choices=("commit", "pr"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=600)
    parser.add_argument("--endpoint", default=os.getenv("OPENAI_API_ENDPOINT", DEFAULT_ENDPOINT))
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--safe-mode", action="store_true", help="민감정보 마스킹 및 diff 전송량 제한")
    parser.add_argument("--safe-max-files", type=int, help="safe mode에서 전송할 최대 파일 수 (기본값: 10)")
    parser.add_argument("--safe-max-lines", type=int, help="safe mode에서 전송할 최대 diff 줄 수 (기본값: 200)")
    parser.add_argument("--safe-mask-regex", action="append", default=[], metavar="REGEX=>REPLACEMENT", help="safe mode에 추가할 마스킹 규칙. 여러 번 지정 가능")
    parser.add_argument("--convention", default=DEFAULT_CONVENTION_FILE, help="커밋/PR 컨벤션 YAML 파일 경로")
    return parser.parse_args()


def print_result(command: str, result: str) -> None:
    print("[DONE] 생성 완료")
    print("\n--- Commit Message ---" if command == "commit" else "\n--- PR Draft ---")
    print(result)
    print("----------------------")


def run() -> int:
    args = parse_args()
    try:
        convention = load_convention(args.convention)
        safe_config = build_safe_config(args, convention)
        status, diff, line_count = git_context(args.safe_mode, safe_config)
        if not status:
            print("[INFO] 변경 사항이 없습니다. 생성을 종료합니다.")
            return 0

        print(f"[INFO] Git status 수집 완료: {len(status.splitlines())}개 항목")
        print(status)
        print(f"[INFO] Git diff 수집 완료: {line_count}줄")
        print("[INFO] AI API 요청 중... (1회)")
        prompt = build_prompt(args.command, status, diff, convention)
        result = normalize_result(args.command, call_api(prompt, args), convention)
        print_result(args.command, result)
        return 0
    except APP_ERRORS as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
