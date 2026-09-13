# AI Git Generator

현재 Git 변경 사항을 AI에 전달해 커밋 메시지 또는 Pull Request 초안을 생성하는 터미널 CLI입니다. `commit`과 `pr` 명령은 각각 AI API를 한 번만 호출합니다.

## 요구 사항

- Python 3.10 이상
- Git 저장소
- 예제 API 서버에서 발급한 API 키

## 설치 및 실행

별도 패키지 설치 없이 실행할 수 있습니다.

```bash
export AI_API_KEY="YOUR_KEY"
python3 main.py commit
python3 main.py pr
```

`.env`를 사용하는 경우 변수명을 반드시 `AI_API_KEY`로 작성하고 셸 환경에 로드합니다.

```bash
# .env
AI_API_KEY="YOUR_KEY"

set -a
source .env
set +a
python3 main.py commit
```

`set -a`는 이후에 정의되는 셸 변수를 자동으로 환경변수로 내보내도록 설정합니다. 따라서 `source .env`로 불러온 `AI_API_KEY`를 Python 프로그램에서도 사용할 수 있습니다. `set +a`는 이 자동 내보내기 설정을 다시 해제합니다.

API 키는 코드나 커밋 파일에 저장하지 마세요.

현재 저장소 루트에서 실행해야 하며, 추적 파일의 staged/unstaged 변경과 untracked 파일의 내용을 입력으로 수집합니다. 변경 사항이 없으면 API를 호출하지 않고 종료합니다.

## 옵션

```text
--model MODEL              기본값: gpt-5.4-mini
--temperature NUMBER       기본값: 0.2
--max-tokens NUMBER        기본값: 600
--endpoint URL              기본값: https://copa.codyssey.kr/v1/chat/completions
--timeout SECONDS           기본값: 60
--safe-mode                 민감정보 마스킹, 최대 10개 파일/200줄 전송
```

예를 들어 민감정보가 포함될 가능성이 있는 변경은 다음처럼 실행합니다.

```bash
python3 main.py pr --safe-mode --temperature 0.1
```

safe mode는 API 키, bearer 인증값, token/secret/password 형태의 값과 이메일 주소를 마스킹하고 diff를 제한합니다. 그래도 생성 결과와 전송 전 diff를 사용자가 검토해야 합니다. API 호출 비용과 rate limit을 고려해 필요한 명령만 실행하세요.

## 출력 예시

```text
[INFO] Git status 수집 완료: 2개 항목
[INFO] Git diff 수집 완료: 48줄
[INFO] AI API 요청 중... (1회)
[DONE] 생성 완료

--- Commit Message ---
feat: add AI generated Git draft command
- Add commit and PR prompt generation in main.py
- Document safe mode and CLI options
----------------------
```

PR 명령은 다음 형식을 출력합니다.

```text
--- PR Draft ---
Title: feat: add AI generated Git draft command

## Why
- Writing consistent change descriptions takes time.

## What
- Generate a commit message and PR draft from Git changes.

## How to Test
- Run python3 main.py commit and python3 main.py pr.
----------------------
```

생성된 문구는 초안이므로 실제 커밋이나 PR에 적용하기 전에 변경 내용과 사실 관계를 확인하세요. 이 도구는 `git commit`, `git push`, GitHub PR 생성을 자동으로 실행하지 않습니다.

## 오류 처리

API 키 누락, HTTP 인증 오류, 네트워크 오류, 잘못된 API 응답은 원인과 함께 `[ERROR]` 메시지로 출력하고 실패 코드로 종료합니다. API 서버가 다른 주소라면 `--endpoint` 옵션 또는 `OPENAI_API_ENDPOINT` 환경변수로 변경할 수 있습니다.
