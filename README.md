# Telegram Idle Assistant Bot 🇰🇷

텔레그램 그룹 대화를 돕기 위해 제작한 비동기 봇입니다. 기본 챗봇 응답 외에도 Dogdrip 인기글 자동 공유, 관리자 명령어, 대화 로그 관리 등 다양한 기능을 제공합니다.

---

## 주요 기능

- **대화 응답**: `@봇이름` 멘션, 특정 키워드(히시 미라클/히시미라클/미라코), 또는 확률 기반으로 LLM 응답을 생성합니다.
- **자동 유머 전송**: 채팅이 지정 시간 이상 정지하면 도그드립 인기 게시글 링크를 랜덤으로 공유합니다.
- **관리자 명령어** (`/umabot` 하위 명령)
  - 메모리 윈도우/보존 정책 설정 (`memory show/set/retain`)
  - 커스텀 지침 관리 (`guide show/set/clear`)
  - 사용량/쿼터 조회 및 초기화 (`quota show/set/reset`)
  - 저장된 대화 데이터 프리뷰 (`data context`) 및 초기화 (`data reset`)
- **유머 테스트 명령**: `/umahumor`로 즉시 유머 링크를 가져올 수 있습니다.
- **데이터베이스 관리**: SQLite(`chat.db`)에 모든 메시지·설정을 기록하며 자동 마이그레이션을 지원합니다.

---

## 사전 준비

1. **Python 3.12** 이상 설치 (Windows는 [Microsoft Store](https://apps.microsoft.com/) 또는 공식 설치 프로그램 권장)
2. **텔레그램 봇 토큰**: [@BotFather](https://t.me/BotFather)로 생성한 토큰을 `.env`에 저장합니다.
3. **그룹 ID 확인**: 봇을 초대한 그룹의 ID를 `TELEGRAM_GROUP_IDS` 환경변수에 쉼표로 구분해 입력합니다.

> `.env` 파일이 없을 경우 실행 시 `setenv.ensure_env_file()`가 기본 템플릿을 만들어 줍니다.

---

## 설치 및 실행

### 1. 저장소 다운로드

```powershell
git clone https://github.com/Amunage/telegrambot.git
cd telegrambot
```

### 2. 가상환경 생성

- **Windows (PowerShell)**
  ```powershell
  python -m venv .venv
  .\.venv\Scripts\Activate.ps1
  python -m pip install --upgrade pip
  pip install -r requirements.txt
  ```

- **Linux/macOS (bash)**
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  python -m pip install --upgrade pip
  pip install -r requirements.txt
  ```

### 3. 환경 변수 설정

`project/.env` 예시:

| `TELEGRAM_BOT_TOKEN` | BotFather에서 받은 토큰 (필수) |
| `TELEGRAM_GROUP_IDS` | 봇이 응답할 허용 채팅 ID (쉼표로 구분) |
| `TELEGRAM_ADMIN_IDS` | 관리 명령을 사용할 수 있는 사용자 ID (옵션, 비우면 모두 허용) |
| `GEMINI_API_KEY` | 제미나이 API KEY |
| `CONTEXT_MAX_MINUTES` | 컨텍스트 로그에 포함 할 최대 과거 시간 |
| `CONTEXT_MAX_MESSAGES` | 컨텍스트 로그에 포함 할 최대 과거 메세지 |
| `MAX_CALLS_PER_DAY` | 하루 최대 호출 가능 수 |
| `MAX_INPUT_CHARS_PER_DAY` | 하루 최대 입력 가능한 글자 수 |
| `MAX_OUTPUT_TOKENS_PER_DAY` | 하루 최대 출력 가능한 토큰 (추정값) |
| `BOT_IDLE_REPLY_PROB` | 멘션 없이도 랜덤 응답을 허용할 확률 (0~1 사이) |

### 4. 로컬 실행

```powershell
python main.py
```

첫 실행 시 DB(`chat.db`)와 필요한 테이블이 자동으로 생성됩니다.

---

## systemd 배포 (Ubuntu 등 Linux 서버)

1. 서버에 저장소 배치 후 의존성 설치
	```bash
	cd /opt/telegrambot
	python3 -m venv .venv
	source .venv/bin/activate
	pip install -r requirements.txt
	```

2. 서비스 유닛 배치
	```bash
	sudo cp deploy/systemd/telegrambot.service /etc/systemd/system/telegrambot.service
	```

3. 유닛 파일 수정
	- `WorkingDirectory` / `ExecStart` / `EnvironmentFile` 경로를 실제 설치 위치에 맞게 변경
	- `.env` 파일을 동일한 디렉터리에 준비

4. 서비스 등록 및 실행
	```bash
	sudo systemctl daemon-reload
	sudo systemctl enable --now telegrambot.service
	```

5. 상태/로그 확인
	```bash
	systemctl status telegrambot.service
	journalctl -u telegrambot.service -f
	```

> 봇은 단일 asyncio 프로세스로 동작하며, 유머 자동 게시 등 백그라운드 작업은 동일 프로세스 내 코루틴으로 수행됩니다.

---

## 봇 업데이트
```chmod +x update_bot.sh
export REPO_ZIP_URL="https://codeload.github.com/Amunage/telegrambot/zip/refs/heads/main"
./update_bot.sh
```

---

## 명령어 요약

### 일반 사용자
- `/umastart` 또는 `/start` : 간단한 소개 메시지
- `/umahumor` : 최신 도그드립 인기글 링크 1개 전송

### 관리자 전용 (`/umabot ...`)

| 명령 | 설명 |
| --- | --- |
| `memory show` | 현재 메모리 윈도우(분)/개수/보존 정책 확인 |
| `memory set <분> <개수>` | 컨텍스트 윈도우 설정 변경 |
| `memory retain <개수> <일수>` | 메시지 보존 개수/기간 조정 및 즉시 정리 |
| `guide show` | 커스텀 지침 확인 |
| `guide set <텍스트>` | 지침 저장 (900자 이상은 말줄임 표기) |
| `guide clear` | 저장된 지침 삭제 |
| `quota show` | 오늘 사용량과 설정된 한도 출력 |
| `quota set <키> <값>` | 한도 오버라이드 (예: `MAX_CALLS_PER_DAY`) |
| `quota reset ` | [limits|today|all] 한도/사용량 초기화 |
| `data context` | 현재 LLM 컨텍스트 샘플 확인 |
| `data reset` | DB를 초기화 (모든 메시지 삭제) |

---

## 데이터 및 유지보수

- **데이터베이스**: `chat.db`에 메시지·설정·지침을 저장합니다. `store.py`가 자동으로 마이그레이션을 처리합니다.
- **로그 위치**: systemd 사용 시 `journalctl`, 로컬 실행 시 표준 출력 로그를 확인합니다.
- **메시지 정리**: `cleanup_keep_recent_per_chat`, `cleanup_old_messages` 함수가 관리 명령과 연계되어 자동 정리를 수행합니다.
- **VACUUM**: `store.vacuum()` 함수로 DB 조각 정리를 수동 실행할 수 있습니다.

---

## 문제 해결

| 봇이 응답하지 않음 | `.env` 토큰/그룹 ID 확인, 봇이 그룹에 초대되었는지 및 관리자 권한이 필요한지 확인 |
| 명령이 "사용할 수 있는 명령이 아니에요"로 응답 | `/umabot` 하위 명령어 철자를 확인, 관리자 ID인지 확인 |
| 유머 링크가 반복됨 | 최근 전송 목록을 내부에서 캐시하므로 시간이 지나면 자동 회복. 긴 시간 반복 시 네트워크 로그 확인 |
| DB 파일이 생성되지 않음 | 실행 계정의 디렉터리 쓰기 권한 확인, `utils.mainpath` 경로 점검 |

