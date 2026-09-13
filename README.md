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
--safe-mode                 민감정보 마스킹, diff 전송량 제한
--safe-max-files NUMBER     safe mode 최대 파일 수 (기본값: 10)
--safe-max-lines NUMBER     safe mode 최대 diff 줄 수 (기본값: 200)
--safe-mask-regex RULE      추가 마스킹 규칙 (REGEX=>REPLACEMENT), 반복 지정 가능
--convention FILE           기본값: .ai-gitgen.yml
```

예를 들어 민감정보가 포함될 가능성이 있는 변경은 다음처럼 실행합니다.

```bash
python3 main.py pr --safe-mode --temperature 0.1
```

safe mode의 기본 제한을 명령별로 조정할 수도 있습니다.

```bash
python3 main.py commit --safe-mode --safe-max-files 5 --safe-max-lines 80
python3 main.py pr --safe-mode --safe-mask-regex 'internal-[A-Za-z0-9]+=>[REDACTED_INTERNAL]'
```

팀 공통 설정은 컨벤션 파일의 `safe_mode`에 작성합니다. `mask_patterns`는
`정규식=>치환값` 형식이며 여러 규칙을 줄 목록으로 추가할 수 있습니다.

```yaml
safe_mode:
  max_files: 5
  max_lines: 120
  mask_patterns:
    - "(?i)(internal_id\\s*[=:]\\s*)[^\\s]+=>\\1[REDACTED_INTERNAL]"
    - "sk-[A-Za-z0-9]+=>[REDACTED_API_KEY]"
```

CLI 옵션은 컨벤션 파일보다 우선합니다. 기본 마스킹 규칙(API 키, bearer 인증값,
token/secret/password 형태의 값, 이메일 주소)은 항상 적용되고, 사용자 규칙은
그 뒤에 추가 적용됩니다. 제한에 도달하면 diff 끝에 실제 적용된 파일/줄 수가 표시됩니다.

### 커스텀 팀 컨벤션

선택한 이전 미션 저장소 `hyojun-edu/E1-2`의 로컬 커밋 이력을 분석한 결과, 커밋은 `Feat:`, `Fix:`, `Docs:`처럼 **대문자 prefix + 콜론 + 공백**을 사용하고 scope는 표기하지 않았습니다. 메시지는 한국어로 기능을 짧게 설명하는 형태가 많았습니다. 이를 예시 팀 컨벤션으로 정의해 기본 설정 파일 [`.ai-gitgen.yml`](.ai-gitgen.yml)에 반영했습니다.

- 커밋 prefix: `Feat`, `Fix`, `Docs`, `Refactor`, `Test`, `Chore`
- 커밋 scope: 사용하지 않음
- 커밋 본문: 최대 3개 bullet, 제목 최대 72자
- PR 톤: 간결하고 사실 중심
- PR 섹션: `Why`, `What`, `How to Test`, `Checklist`
- `Checklist`도 다른 PR 섹션과 동일하게 변경 내용에 맞춰 생성

설정 파일을 바꾸거나 `--convention`으로 다른 파일을 지정할 수 있습니다.

```bash
python3 main.py commit
python3 main.py pr --convention ./team-convention.yml
```

기본 프롬프트 적용 전에는 `feat: add ...`처럼 소문자 prefix와 고정 PR 섹션을 사용했지만, 적용 후에는 E1-2 스타일에 맞춰 `Feat: ...` 형태를 요청하고 변경 내용에 맞는 `Checklist` 섹션까지 생성합니다.

```text
# 적용 전
feat: add quiz history

# 적용 후 (.ai-gitgen.yml)
Feat: 퀴즈 기록 히스토리 추가

## Checklist
- [ ] 변경 내용을 직접 확인했나요?
- [ ] 테스트 또는 실행 방법을 확인했나요?
```

safe mode는 API 키, bearer 인증값, token/secret/password 형태의 값과 이메일 주소를 마스킹하고 diff를 제한합니다. `safe_mode.mask_patterns` 또는 `--safe-mask-regex`로 정규표현식 기반 규칙을 추가하고, 파일/줄 제한도 조정할 수 있습니다. 그래도 생성 결과와 전송 전 diff를 사용자가 검토해야 합니다. API 호출 비용과 rate limit을 고려해 필요한 명령만 실행하세요.

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

## 동작 원리와 실무 가이드

### 1. AI API를 REST API로 연동하는 전체 흐름

이 프로그램은 Python 표준 라이브러리의 `urllib.request`로 Chat Completions 형태의 REST API를 호출합니다. 흐름은 다음과 같습니다.

1. `AI_API_KEY` 환경변수가 있는지 확인합니다. 키를 코드에 하드코딩하지 않고 실행 환경에서 읽어 인증 정보가 소스와 함께 유출되지 않도록 합니다.
2. Git 상태와 diff를 수집해 AI가 이해할 수 있는 프롬프트를 만듭니다. `commit`은 커밋 메시지 규칙을, `pr`은 PR Markdown 구조를 요청합니다.
3. 다음 JSON payload를 구성해 endpoint에 `POST` 요청을 보냅니다.

   ```json
   {
     "model": "gpt-5.4-mini",
     "temperature": 0.2,
     "max_tokens": 600,
     "messages": [
       {"role": "system", "content": "출력 형식을 정확히 따른다."},
       {"role": "user", "content": "Git status와 Git diff를 바탕으로 작성..."}
     ]
   }
   ```

   헤더에는 `Authorization: Bearer <API_KEY>`와 `Content-Type: application/json`을 넣습니다. `--endpoint`로 서버 주소를 바꿀 수 있고, `--timeout`으로 응답을 기다리는 최대 시간을 제한합니다.
4. 응답 본문을 JSON으로 파싱한 뒤 `choices[0].message.content`를 추출합니다. 앞뒤 공백과 코드 펜스를 제거하고 명령에 맞는 형식으로 정규화해 출력합니다.
5. API 키 누락, HTTP 오류, 네트워크·timeout 오류, JSON 파싱 오류, 예상하지 못한 응답 구조는 원인을 포함한 `[ERROR]`로 알리고 실패 코드 `1`로 종료합니다. 변경 사항이 없으면 API를 호출하지 않고 성공 코드 `0`으로 종료합니다.

### 2. 주요 생성 파라미터와 결과 품질

| 파라미터 | 역할과 영향 | 이 도구에서의 기준 |
| --- | --- | --- |
| `temperature` | 무작위성을 조절합니다. 낮추면 표현이 일관되고 사실 중심이 되며, 높이면 다양해지지만 diff에 없는 내용을 추측할 위험이 커집니다. | 기본값 `0.2`. 정확성과 재현성이 중요한 커밋·PR에는 낮은 값을 권장합니다. |
| `max_tokens` | 한 응답에 생성할 수 있는 최대 토큰 수입니다. 높인다고 내용이 자동으로 좋아지지는 않으며, 너무 낮으면 제목이나 섹션이 잘릴 수 있습니다. | 기본값 `600`. 출력 형식과 변경량에 맞춰 조정합니다. |
| `model` | 지시 이해력, 요약 품질, 속도와 비용에 영향을 줍니다. | `--model`로 서버가 지원하는 모델을 선택합니다. |
| `timeout` | 품질 파라미터가 아니라 응답 대기 시간의 상한입니다. 너무 짧으면 정상 요청도 실패할 수 있습니다. | 기본값 `60`초입니다. |

실무에서는 먼저 낮은 `temperature`로 사실에 충실한 결과를 얻고, 출력이 잘리는 경우에만 `max_tokens`를 늘립니다. 값을 과도하게 높이면 요구사항 위반이나 추측성 문장이 늘어날 수 있습니다.

### 3. Git 명령 결과를 프로그램 입력으로 연결하는 방식

프로그램은 셸 명령 결과를 사람이 복사해 붙이는 대신 `subprocess.run(["git", ...])`으로 직접 실행합니다. `git rev-parse --show-toplevel`로 저장소 루트를 찾은 뒤 다음 결과를 수집합니다.

- `git status --short`: 변경 파일 목록과 상태를 가져옵니다. 결과가 비어 있으면 API를 호출하지 않습니다.
- `git diff HEAD`: HEAD 기준 staged/unstaged 추적 파일의 변경을 가져옵니다. 아직 HEAD가 없는 초기 저장소에서는 `git diff`와 `git diff --cached`를 합칩니다.
- untracked 파일: `git diff`에 포함되지 않으므로 `status`의 `??` 항목을 찾아 파일 내용을 별도로 읽어 문맥에 덧붙입니다.

수집한 `status`와 `diff` 문자열을 프롬프트 입력으로 전달하는 것이 자동화의 핵심입니다. `--safe-mode`에서는 API 키·token·secret·password·bearer 값과 이메일을 마스킹하고 전송 diff를 기본 최대 10개 파일·200줄로 제한합니다. `safe_mode` 설정 또는 CLI 옵션으로 이 정책과 추가 정규식 규칙을 바꿀 수 있습니다. 즉, Git 명령 실행 → 결과 수집·보호 → 프롬프트 삽입 → API 요청의 흐름입니다. `subprocess` 오류도 `GitError`로 바꿔 원인을 표시합니다.

### 4. Commit/PR 양식과 변경 맥락을 반영하는 프롬프트 구성

좋은 프롬프트는 “요약해 줘”에 그치지 않고 출력 계약과 근거를 함께 제공합니다.

1. **역할과 목적**: system 메시지에서 Git 텍스트를 정확히 생성하고 요청 형식을 따르도록 역할을 고정합니다.
2. **출력 형식**: commit은 최대 72자의 제목과 선택적인 1~3개 bullet, `feat`·`fix`·`refactor`·`docs` 같은 conventional prefix를 명시합니다. PR은 최대 80자의 `Title`과 설정된 섹션을 정확히 요구합니다.
3. **변경 맥락**: `Git status`와 `Git diff`를 함께 넣어 파일명, 변경 범위, 테스트 방법처럼 실제 변경에서 확인 가능한 근거를 제공합니다.
4. **추측 방지**: 실제 변경을 사용하고 합리적인 테스트 명령을 작성하라고 지시해 diff에 없는 기능이나 검증 결과를 만들지 않도록 합니다.

status는 “무엇이 바뀌었는가”, diff는 “어떻게 바뀌었는가”를 보여주므로 둘을 함께 넣어야 제목·이유·변경 내용·테스트 방법이 서로 어긋나지 않습니다.

### 5. 생성 결과 검증과 후처리

AI 출력은 확률적으로 생성되므로 그대로 실무 산출물로 사용하지 않고 규칙을 검증·보정해야 합니다.

- 공백과 코드 펜스를 제거해 복사하기 쉬운 텍스트로 만듭니다.
- commit 제목을 첫 줄에서 가져와 72자로 제한하고, 뒤의 최대 3개 줄을 bullet 형식으로 정리합니다.
- PR 제목을 `Title:`에서 추출해 80자로 제한하고 설정된 섹션을 모두 유지합니다. 누락된 섹션이나 bullet은 기본 안내 문구로 보완합니다.
- 지정하지 않은 PR 섹션이 출력되어도 설정된 섹션만 남겨 템플릿을 지킵니다.

이 검증은 길이 초과, 섹션 누락, Markdown 형식 불일치로 다시 수작업할 비용을 줄입니다. 다만 길이를 자르는 것만으로 의미가 보장되지는 않으므로, 최종 적용 전에는 실제 diff와 대조해 제목이 핵심 변경을 설명하는지, 테스트 명령이 실제로 존재하는지, 민감정보나 과장된 표현이 없는지 확인해야 합니다. 필요하면 형식 지시를 구체화하거나 `temperature`를 낮추고, 출력이 잘리는 경우에만 `max_tokens`를 조정합니다.

## 오류 처리

API 키 누락, HTTP 인증 오류, 네트워크 오류, 잘못된 API 응답은 원인과 함께 `[ERROR]` 메시지로 출력하고 실패 코드로 종료합니다. API 서버가 다른 주소라면 `--endpoint` 옵션 또는 `OPENAI_API_ENDPOINT` 환경변수로 변경할 수 있습니다.

## 보너스 과제
### 1. 실제 리포지토리에 적용하여 PR 1건 완성하기
- "의미 있는 변경"을 improve-comment branch에서 수행
- commit message 생성
```
% python3 main.py commit --convention ./.ai-gitgen.yml
[INFO] Git status 수집 완료: 1개 항목
M main.py
[INFO] Git diff 수집 완료: 66줄
[INFO] AI API 요청 중... (1회)
[DONE] 생성 완료

--- Commit Message ---
Docs: 정규식 마스킹 및 PR 정규화 로직 주석 추가
----------------------
```
- pr message 생성
```
% python3 main.py pr --convention ./.ai-gitgen.yml
[INFO] Git status 수집 완료: 2개 항목
M README.md
 M main.py
[INFO] Git diff 수집 완료: 88줄
[INFO] AI API 요청 중... (1회)
[DONE] 생성 완료

--- PR Draft ---
Title: Docs: 정규식 마스킹 및 PR 정규화 로직 주석 추가

## Why
- 정규식 마스킹과 PR 텍스트 정규화 로직의 동작 의도를 코드와 문서에서 더 명확히 드러내기 위해서입니다.
- README 예시의 출력 내용을 현재 동작에 맞게 갱신하기 위해서입니다.

## What
- `main.py`의 `mask_secrets`, `clean_text`, `normalize_pr`에 정규식 동작과 처리 범위를 설명하는 주석을 추가했습니다.
- 동적 마스킹 정규식을 사전 컴파일해 문법 오류를 조기에 확인하는 흐름을 주석으로 명시했습니다.
- `README.md`의 예시 커밋 메시지와 출력 줄 수를 현재 변경 내용에 맞게 수정했습니다.

## How to Test
- `python3 main.py commit --convention ./.ai-gitgen.yml` 실행 후 커밋 메시지 생성이 정상인지 확인합니다.
- `python3 main.py pr --convention ./.ai-gitgen.yml` 실행 후 PR 제목과 섹션 추출이 정상인지 확인합니다.
- `python3 -m py_compile main.py`로 문법 오류가 없는지 확인합니다.

## Checklist
- [x] 문서와 코드 주석이 실제 동작과 일치합니다.
- [x] README 예시가 최신 출력과 맞습니다.
- [x] 기존 기능 변경 없이 설명만 보강했습니다.
----------------------
```
- 실제 PR 링크: https://github.com/hyojun-edu/B3-2/pull/2
- “AI 초안 → 최종 PR” 변경점 요약
  1. "README.md의 예시 커밋 메시지와 출력 줄 수를 현재 변경 내용에 맞게 수정했습니다." 라는 내용이 있었는데, 실제 수정은 main.py에만 있었고 README는 수정사항이 없었음. 환각에 의한 내용이므로 삭제.
  2. 마찬가지로 "-EADME 예시의 출력 내용을 현재 동작에 맞게 갱신하기 위해서입니다." 부분도 README 에서의 출력 내용에 대해서 갱신된 변경사항이 전혀 없었으므로 삭제.
  3. "동적 마스킹 정규식을 사전 컴파일해 문법 오류를 조기에 확인하는 흐름을 주석으로 명시했습니다."은 이번 변경사항이 정규식이 어떤 동작을 하는지를 설명하는 주석을 다는 것이기에 의도에서 벗어난 설명이므로 삭제.


### 2. 커밋/PR 템플릿 커스터마이징
- 컨벤션 문서 예시
```
# E1-2에서 확인한 팀 커밋 스타일을 재현하는 예시 설정입니다.
language: 한국어
commit:
  prefixes: [Feat, Fix, Docs, Refactor, Test, Chore]
  scope: false
  max_title_length: 72
  body_bullets: 3
pr:
  tone: 간결하고 사실 중심
  title_prefix: true
  sections:
    - Why
    - What
    - How to Test
    - Checklist
```
- 컨벤션 적용 전/후 생성 결과 비교
 1. 컨벤션 적용 전
```
% python3 main.py pr 
[INFO] Git status 수집 완료: 3개 항목
D .ai-gitgen.yml
 M README.md
?? .ai-gitgen_custom.yml
[INFO] Git diff 수집 완료: 102줄
[INFO] AI API 요청 중... (1회)
[DONE] 생성 완료

--- PR Draft ---
Title: Update README with custom commit and PR template example

## Why
- Document the custom commit and PR convention example in the repository.
- Keep the README aligned with the new `.ai-gitgen_custom.yml` configuration.

## What
- Added a new `.ai-gitgen_custom.yml` file with the team-style commit and PR settings.
- Updated `README.md` to include the customization example and the before/after generation output.
- Removed the old `.ai-gitgen.yml` example file.
----------------------
```
 2. 컨벤션 적용 후
```
% python3 main.py pr --convention .ai-gitgen_custom.yml 
[INFO] Git status 수집 완료: 3개 항목
D .ai-gitgen.yml
 M README.md
?? .ai-gitgen_custom.yml
[INFO] Git diff 수집 완료: 122줄
[INFO] AI API 요청 중... (1회)
[DONE] 생성 완료

--- PR Draft ---
Title: Docs: 커밋·PR 템플릿 예시와 설정 파일 정리

## Why
- 커밋/PR 작성 규칙 예시를 별도 설정 파일로 분리해 재사용성을 높이기 위함입니다.
- README의 예시와 실제 설정 파일 구성을 현재 변경 내용에 맞게 정리하기 위함입니다.

## What
- 기존 `.ai-gitgen.yml` 예시 파일을 삭제했습니다.
- 동일한 커밋/PR 컨벤션 예시를 담은 `.ai-gitgen_custom.yml`을 추가했습니다.
- README에 커밋/PR 템플릿 커스터마이징 예시와 적용 전/후 생성 결과를 추가했습니다.

## How to Test
- `git status`로 삭제된 파일과 신규 파일, README 변경을 확인합니다.
- `git diff -- README.md .ai-gitgen_custom.yml`로 변경 내용을 검토합니다.
- `python3 main.py pr --convention ./.ai-gitgen.yml`로 문서 예시와 생성 결과를 확인합니다.

## Checklist
- [x] 설정 파일 변경 사항을 문서에 반영했습니다.
- [x] README 예시는 실제 변경 내용과 일치합니다.
- [x] PR 제목 형식을 지정된 접두사 규칙에 맞췄습니다.
----------------------
```
