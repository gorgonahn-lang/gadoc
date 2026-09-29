# gadoc

**grok(Grok Build)과 Antigravity CLI(agy) 전용 하네스 점검 도구.**
두 에이전트가 세션마다 불러오는 스킬·플러그인·MCP 서버·훅·규칙 파일을 읽기만 해서 점검하고, 사용자가 승인한 항목만 되돌릴 수 있게 정리합니다.

[English](#english)

## 왜 필요한가

- grok은 자체 스킬뿐 아니라 Claude Code의 스킬·플러그인·`CLAUDE.md`·MCP 설정까지 함께 불러옵니다. 모르는 사이 수십 개의 스킬 설명이 매 요청에 실립니다.
- agy는 전역·작업공간·플러그인·내장 스킬이 우선순위에 따라 겹치고, 규칙 파일에는 크기 상한(파일당 24KB, 전체 약 2만 토큰)이 있습니다.
- `grok doctor`는 터미널 환경만, `grok mcp doctor`는 MCP만 보고, agy에는 점검 명령이 없습니다. Claude Code·Codex용 점검 도구는 grok·agy 경로를 모릅니다.

## 구성

| 스킬 | 역할 |
|---|---|
| `gadoc` | 읽기 전용 점검. 수집 스크립트로 인벤토리 JSON을 만들고, 깨진 항목·잘리는 규칙·권한 자동 허용·이름 그림자(shadowing)·기능 중복·규칙 충돌·불필요한 노출을 보고합니다 |
| `gadoc-trim` | 승인 기반 정리. 변경 계획표 → 승인 → 백업/격리(park)/명령 기록 → 적용 → 재점검. `rollback` 한 줄로 되돌립니다 |

```
skills/
  gadoc/        SKILL.md, references/checks.md, scripts/collect.py
  gadoc-trim/   SKILL.md, references/levers.md, scripts/snapshot.py
install.sh
```

필요한 것: macOS 또는 Linux, `python3`(3.9+, 표준 라이브러리만 사용), grok 및/또는 agy.

## 설치

```bash
git clone https://github.com/gorgonahn-lang/gadoc.git ~/gadoc
bash ~/gadoc/install.sh            # grok과 agy 모두
bash ~/gadoc/install.sh --grok-only
bash ~/gadoc/install.sh --agy-only
bash ~/gadoc/install.sh --uninstall
```

설치 스크립트는 스킬 폴더를 링크만 합니다.
- grok: `~/.grok/skills/gadoc`, `~/.grok/skills/gadoc-trim`
- agy: `~/.gemini/config/skills/gadoc`, `~/.gemini/config/skills/gadoc-trim`

`~/.claude`나 `~/.agents`에는 설치하지 않으므로 Claude Code·Codex에는 보이지 않습니다.

## 사용

새 grok 또는 agy 세션에서:

```
gadoc으로 하네스 점검해줘          # grok에서는 /gadoc 도 가능
gadoc 보고서대로 정리해줘           # gadoc-trim: 계획표를 보여주고 승인받은 것만 적용
gadoc-trim 마지막 변경 되돌려줘
```

에이전트 없이 수집기만 돌릴 수도 있습니다.

```bash
python3 ~/gadoc/skills/gadoc/scripts/collect.py --project . --summary
python3 ~/gadoc/skills/gadoc-trim/scripts/snapshot.py list
python3 ~/gadoc/skills/gadoc-trim/scripts/snapshot.py rollback <ID> --run-undo
```

보고서와 인벤토리는 `~/.gadoc/reports/`, 변경 백업은 `~/.gadoc/backups/<ID>/`에 남습니다.

## 안전 원칙

- `gadoc`은 아무것도 바꾸지 않습니다. 수집기는 비밀값(`env`, `headers`, key/token 류)을 `***`로 가립니다.
- `gadoc-trim`은 파일을 지우지 않습니다. 설정은 백업 후 수정, 스킬 폴더는 격리(park), CLI 토글은 되돌리는 명령과 함께 기록합니다.
- grok이 물려받은 Claude Code 항목은 `~/.claude`를 건드리지 않고 grok 쪽 설정(`[skills].ignore`, `[plugins].disabled`)으로만 숨깁니다.
- agy 내장 스킬은 보고만 하고 건드리지 않습니다.

## 참고

"읽기 전용 점검 + 승인 후 정리"라는 접근은 Claude Code·Codex용 [HarDoc](https://github.com/qjc-office/hardoc)에서 착안했습니다. gadoc은 HarDoc의 코드나 문서를 사용하지 않은 독립 구현이며, HarDoc과 제휴 관계가 없습니다.

## License

MIT - [LICENSE](LICENSE)

---

## English

**gadoc** is a harness checkup for **grok (Grok Build)** and **Antigravity CLI (agy)**.

- `gadoc` - read-only audit. A collector (`scripts/collect.py`, stdlib Python 3.9+) snapshots skills, plugins, MCP servers, hooks, rule files and shell aliases for both harnesses (using `grok inspect --json`, `grok mcp doctor --json`, `agy plugin list`, `agy mcp list` and a filesystem scan), redacts secrets and emits mechanical findings. The agent then checks overlap, rule conflicts and unneeded exposure and writes an evidence-backed report.
- `gadoc-trim` - approval-gated cleanup. Plan table, explicit approval, journaled changes (`scripts/snapshot.py`: backup, park, record) and one-command rollback.

Install with `bash install.sh` (links into `~/.grok/skills` and `~/.gemini/config/skills`), then ask a new grok or agy session: "audit my harness with gadoc". Inspired by the approach of HarDoc for Claude Code/Codex; independent implementation, not affiliated. MIT licensed.
