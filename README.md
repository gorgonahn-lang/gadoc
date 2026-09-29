# gadoc

> **gadoc! grok이랑 agy 하네스, 지금 엉망이야. 당장 고쳐!**

**gadoc은 [HarDoc](https://github.com/qjc-office/hardoc)의 grok(Grok Build)·Antigravity CLI(agy) 버전입니다.** HarDoc이 Claude Code·Codex에서 하는 일을, grok과 agy의 실제 설정 경로와 명령에 맞춰 똑같이 합니다. HarDoc 저작자의 허락을 받아 만든 파생 작업입니다([NOTICE](NOTICE)).

[English](#english)

AI 어시스턴트가 엉뚱한 스킬을 고르거나, 같은 도구를 두 번 보거나, 필요 없는 것을 불러오느라 시간을 쓰게 만드는 지시문과 도구를 찾아 주는 **읽기 전용 하네스 점검**입니다.

## 30초 설명

AI 코딩 환경을 공구함이라고 생각해 보세요.

- **스킬**은 어시스턴트에게 어떤 일을 하는 방법을 알려 주는 레시피입니다.
- **MCP 서버**는 외부 도구나 데이터로 가는 다리입니다.
- **플러그인**은 스킬과 다른 구성 요소를 묶은 꾸러미입니다.
- **훅**은 특정 시점에 자동으로 실행되는 동작입니다.
- **규칙**(`AGENTS.md`, `GEMINI.md`, `CLAUDE.md`)이나 **에이전트**는 상시 지시문이나 전문 역할을 더합니다.

항목이 많다고 어시스턴트가 똑똑해지지는 않습니다. 설명이 비슷한 스킬끼리 경쟁하고, 지시문이 서로 어긋나고, 늘 노출되는 항목은 매 요청에 잡음을 더합니다. gadoc은 가장 작고 안전한 정리를 제안하기 전에 증거부터 모읍니다.

grok과 agy에는 특히 이런 사정이 있습니다.
- **grok**은 자체 스킬뿐 아니라 Claude Code의 스킬·플러그인·`CLAUDE.md`·MCP 설정까지 함께 불러옵니다. 모르는 사이 수십 개의 스킬 설명이 매 요청에 실립니다.
- **agy**는 작업공간·전역·플러그인·내장 스킬이 우선순위에 따라 겹치고, 규칙 파일에는 크기 상한(파일당 24KB, 전체 약 2만 토큰)이 있습니다.
- `grok doctor`는 터미널 환경만 점검하고, agy에는 doctor 명령이 아예 없습니다.

## 언제 쓰면 좋은가

- 어시스턴트가 자꾸 엉뚱한 스킬을 고를 때
- 두 스킬이 같은 일을 하는 것처럼 보일 때
- 새 플러그인이나 MCP 서버를 넣은 뒤 세션이 느려지거나 시끄러워졌을 때
- 규칙, 훅, 에이전트가 서로 어긋나 보일 때
- 무언가를 지우고 싶은데 안전하다는 증거가 필요할 때
- 하네스를 바꾼 뒤 실제 작업이 나빠지지 않았는지 확인하고 싶을 때

## 안전 약속

gadoc은 승인 없이 아무것도 바꾸지 않습니다.

`gadoc`은 읽기 전용입니다. 보고만 하고, 삭제·비활성화·설치·설정 수정·doctor 자동 수정(`grok doctor fix`)·메시지 전송을 하지 않습니다. "정리 후보" 같은 결과는 사람이 검토할 제안입니다. 수집기는 비밀값(`env`, `headers`, key/token 류, URL 쿼리)을 `***`로 가립니다.

`gadoc-trim`은 설정을 바꿀 수 있지만, 먼저 보여 준 변경 목록을 승인한 뒤에만 바꿉니다. 쓰기 전에 건드릴 모든 파일을 스냅샷으로 남기고, 끝나면 모두 되돌리는 명령 하나를 알려 줍니다. 아무것도 설치하지 않고, 프로젝트 소스를 고치지 않으며, 이름을 대서 요청하지 않는 한 훅과 에이전트는 건드리지 않습니다. grok이 물려받은 Claude Code 항목은 `~/.claude`를 건드리지 않고 grok 쪽 설정으로만 숨깁니다.

## 설치

```bash
git clone https://github.com/gorgonahn-lang/gadoc.git ~/gadoc
bash ~/gadoc/install.sh              # grok과 agy 모두
bash ~/gadoc/install.sh --grok-only  # 또는 --agy-only
bash ~/gadoc/install.sh --uninstall
```

설치 스크립트는 두 스킬 폴더를 링크만 합니다.
- grok: `~/.grok/skills/gadoc`, `~/.grok/skills/gadoc-trim`
- agy: `~/.gemini/config/skills/gadoc`, `~/.gemini/config/skills/gadoc-trim`

`~/.claude`나 `~/.agents`에는 설치하지 않으므로 Claude Code·Codex에는 보이지 않습니다. 업데이트는 `cd ~/gadoc && git pull` 한 번이면 두 도구 모두에 적용됩니다.

새 grok 또는 agy 세션을 열고 실행합니다.

```text
/gadoc audit .                 # grok
gadoc audit .                  # agy (또는 "gadoc으로 하네스 점검해줘")
```

필요한 것: macOS 또는 Linux, `python3` 3.9 이상(표준 라이브러리만 사용), grok 및/또는 agy.

## `audit`이 점검하는 것

먼저 대상 폴더를 검증합니다. 그다음 런타임 버전과 지원되는 도움말을 확인한 뒤, 해당 doctor와 목록 명령을 실행합니다.

| 런타임 | doctor 점검 | 그 밖의 증거 |
| --- | --- | --- |
| grok | `grok doctor`(터미널만), `grok mcp doctor --json` | `grok inspect --json`: 스킬, MCP, 플러그인, 훅, 규칙, 에이전트, 권한 |
| agy | 없음 → `UNSUPPORTED` | `agy plugin list`, `agy mcp list`, 파일 스캔: 스킬, MCP, 플러그인, 훅, 규칙 |

보고서는 다음 질문을 따로따로 다룹니다.

1. 설치되어 있는가?
2. 활성화되어 세션에 노출되는가?
3. 실제로 선택되거나 호출되었는가? (이 컴퓨터의 세션 기록에서 스킬 파일을 실제로 불러온 흔적)
4. 남겨 둘 의존성이나 안전상의 이유가 있는가?
5. 제안한 변경 뒤에도 실제 작업이 통과했는가?

doctor가 성공했다고 모든 작업이 정확하다는 증거가 되지는 않습니다. doctor 결과는 건강 상태의 증거이고, 작업 자체는 따로 회귀 점검이 필요합니다.

## 세 가지 모드

| 모드 | 의미 | 언제 |
| --- | --- | --- |
| `audit` | 읽기 전용으로 증거를 모으고 분류 | 여기서 시작 |
| `propose` | 증거를 복구 방법이 딸린 최소 변경 제안으로 정리 | audit이 실제 후보를 찾은 뒤 |
| `evaluate` | 기준과 후보를 같은 실제 작업으로 비교 | 개선됐다고 말하기 전 |

평가는 두 조건에 같은 호스트, 모델, 권한, 작업 프롬프트를 씁니다. grok은 임시 `GROK_HOME`으로 후보 설정을 격리해 실제 설정을 건드리지 않고 비교합니다. agy는 전역 설정을 격리할 공식 방법이 없어, 전역 항목을 바꾸는 후보는 `UNVERIFIED`로 남깁니다. 잘못된 선택, 필요한 스킬 누락, 지시문 충돌, 작업 결과를 따로 셉니다. 토큰 수나 지연 시간만으로는 정확도 결과가 아닙니다.

## `gadoc-trim`으로 정리하기

`gadoc`은 제안에서 멈춥니다. 실제로 실행하는 것은 `gadoc-trim`입니다.

```text
/gadoc-trim --dry-run
```

이 컴퓨터에서 하는 일에 대해 최대 네 가지를 묻고(`~/.gadoc/profile.json`에 저장), 매 세션 불러오는 모든 것을 그 답과 대조해 순위를 매긴 뒤, 쓰기 전에 표를 먼저 보여 줍니다. 원하는 것만 승인하면 그것만 적용합니다.

기본 처방은 삭제가 아닙니다. grok과 agy 모두 스킬 파일 머리말의 `disable-model-invocation: true`로 **모델의 스킬 목록에서만 빼고 스킬은 살려 둘 수 있습니다**. grok 1.0.41과 agy 1.2.13에서 검증했고, grok에서는 `/이름`으로 계속 부를 수 있습니다(agy의 직접 호출은 미확인). 이 단계의 잘못된 추측은 거의 비용이 없습니다. 삭제 수준(`off`) 변경은 요청할 때만 합니다.

이 스킬별 수단은 사용자가 소유한 스킬 폴더에만 닿습니다.
- **플러그인이 준 스킬**: 플러그인 전체를 끄는 수밖에 없습니다(grok `[plugins].disabled`, agy `agy plugin disable`).
- **grok이 Claude Code에서 물려받은 스킬**: `~/.claude`를 건드리면 Claude Code까지 바뀌므로 grok의 `[skills].ignore`로만 숨깁니다.
- **내장 스킬**: 건드리지 않습니다.

훅과 에이전트는 opt-in입니다. 공식적으로 끄는 스위치가 없어서, 끄려면 설정 파일에서 항목을 잘라 내거나 파일을 옮겨야 하기 때문입니다. `--include-hooks`를 줄 때만 합니다.

```text
/gadoc-trim restore 20260929-133155
```

되돌리기는 각 파일을 스냅샷과 비교합니다. 스냅샷 이후 직접 고친 것이 있으면 덮어쓰지 않고 충돌로 알려 줍니다. 옮긴 폴더는 스냅샷 밖(`~/.gadoc/held/`)에 보관되므로, 스냅샷을 지워도 사라지지 않습니다.

컨텍스트가 작아졌다고 자동으로 더 좋아진 것은 아닙니다. 정확도가 실제로 좋아졌는지 알고 싶으면 `gadoc evaluate`로 실제 작업을 비교하세요.

## 보고서 읽는 법

- **Keep(유지)**: 여전히 필요하다는 증거가 있습니다.
- **Cleanup candidate(정리 후보)**: 단순화할 여지가 있지만, 의존성과 복구 방법을 사람이 검토해야 합니다.
- **Fix candidate(수정 후보)**: 고장 났거나 재현 가능한 문제를 일으킵니다.
- **Insufficient observation(관찰 부족)**: 판단하기에 데이터가 부족합니다.

doctor 상태도 명시합니다.

- `COMPLETED`는 명령이 끝났다는 뜻일 뿐, 하네스가 건강하다는 뜻이 아닙니다.
- `UNSUPPORTED`, `ERROR`, `TIMEOUT`, `NOT_RUN`이면 doctor 검증은 `UNVERIFIED`입니다.

경로가 없거나 폴더가 아니라 파일이면, gadoc은 오류를 보고하고 상위 폴더나 홈 폴더를 몰래 대신 스캔하지 않습니다.

## 처음 써 보는 순서

1. 점검할 프로젝트를 엽니다.
2. `install.sh`로 grok·agy에 설치합니다.
3. 스킬 목록을 다시 불러오도록 새 세션을 엽니다.
4. grok에서 `/gadoc audit .`, agy에서 `gadoc audit .`를 실행하고 보고서를 기다립니다.
5. doctor 상태부터 읽습니다.
6. 정리 후보와 그 근거를 검토합니다.
7. 그다음에야 제안을 만들고 실제 작업으로 평가합니다.
8. 실행하고 싶으면 `/gadoc-trim --dry-run`으로 표를 읽은 뒤 승인합니다.

관찰된 호출 수가 0이라는 이유만으로 지우지 마세요. 드물게 필요하거나, 다른 컴퓨터에서만 쓰이거나, 프로젝트 파일이 직접 불러오는 것일 수 있습니다.

## 호환성 메모

- 스킬 이름은 `gadoc`(진단)과 `gadoc-trim`(승인 후 적용)입니다. HarDoc의 `skill-governor`, `trim`과 이름이 겹치지 않아, grok이 Claude Code의 HarDoc을 함께 불러와도 충돌하지 않습니다.
- grok과 agy는 따로 점검합니다. 한 런타임의 결과를 다른 런타임에 옮겨 적지 않습니다.
- CLI 버전이 doctor 명령이나 출력 옵션을 지원하지 않으면, gadoc은 추측하지 않고 그 사실을 기록합니다.
- 터미널 래퍼(예: cmux 셸 스크립트)가 `PATH` 앞쪽에 있으면 실제 바이너리로 진단하고 래퍼는 따로 기록합니다.
- 최근 사용 증거는 이 컴퓨터의 세션 기록에서만 나옵니다. grok은 `~/.grok/sessions/`, agy는 `~/.gemini/antigravity-cli/brain/`를 봅니다. gadoc 점검 세션은 다른 스킬을 일부러 읽으므로 제외합니다.
- Claude Code·Codex는 원본 [HarDoc](https://github.com/qjc-office/hardoc)을 쓰세요.

## 구성

```
skills/
  gadoc/        SKILL.md, references/{harness-audit,evaluation,checks}.md, scripts/collect.py
  gadoc-trim/   SKILL.md, references/{profile,levers}.md, scripts/snapshot.py
install.sh
```

## 출처와 라이선스

gadoc은 HarDoc(QuantumJumpClub, https://github.com/qjc-office/hardoc)의 grok·agy 버전으로, HarDoc 저작자의 허락을 받아 그 내용을 옮기고 grok·agy에 맞게 고쳤습니다. 자세한 내용은 [NOTICE](NOTICE)를 보세요. gadoc이 새로 작성한 코드는 [MIT](LICENSE)입니다.

---

## English

**gadoc is the grok (Grok Build) and Antigravity CLI (agy) edition of [HarDoc](https://github.com/qjc-office/hardoc)**, adapted with the HarDoc author's permission. It keeps HarDoc's design - a read-only checkup (`gadoc`: `audit`, `propose`, `evaluate`) and an approval-gated cleanup with one-command rollback (`gadoc-trim`: `--dry-run`, `--reprofile`, `--include-hooks`, `--level off`, `restore <id>`) - and maps every runtime surface to grok and agy:

- Doctor/listing: `grok doctor` (terminal only), `grok mcp doctor --json`, `grok inspect --json`; agy has no doctor (`UNSUPPORTED`), so `agy plugin list`, `agy mcp list` and a filesystem scan are used.
- A stdlib-Python collector verifies the target path, records host/version/wrappers, masks secrets, and records per item: installed, enabled, exposed, invoked (skill loads in this host's grok/agy session logs), standing cost, hash and invocation policy.
- Lowest lever: `disable-model-invocation: true` in a skill's frontmatter removes it from the model's listing (verified on grok 1.0.41 and agy 1.2.13; `/name` still works in grok). Plugins are turned off as a whole (`[plugins].disabled`, `agy plugin disable`); items grok inherits from Claude Code are hidden grok-side (`[skills].ignore`) and `~/.claude` is never edited.
- Evaluation isolates grok candidates in a temporary `GROK_HOME`; agy global changes cannot be isolated and stay `UNVERIFIED`.

Install: `git clone https://github.com/gorgonahn-lang/gadoc.git ~/gadoc && bash ~/gadoc/install.sh`, then in a new session run `/gadoc audit .` (grok) or `gadoc audit .` (agy). See [NOTICE](NOTICE) for attribution; new code is MIT.
