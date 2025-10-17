
from pathlib import Path
from textwrap import dedent

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

DEFAULT_ENV_TEMPLATE = dedent(
    """
    # TELEGRAM 봇 토큰과 Gemini API 키를 환경변수로 설정하세요.
    TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
    GEMINI_API_KEY=YOUR_GEMINI_API_KEY

    # 컨텍스트/페르소나 기본값
    CONTEXT_MAX_MINUTES=60
    CONTEXT_MAX_MESSAGES=100

    # 관리자 및 허용 채팅방 ID (쉼표로 구분)
    TELEGRAM_ADMIN_IDS=
    TELEGRAM_GROUP_IDS=

    # 사용량 제한 기본값
    MAX_CALLS_PER_DAY=100
    MAX_INPUT_CHARS_PER_DAY=100000
    MAX_OUTPUT_TOKENS_PER_DAY=20000

    # db 파일 경로
    CHAT_DB_PATH=chat.db
    USAGE_DB_PATH=usage.db

    # 자발적 응답 확률 (0.0~1.0)
    BOT_IDLE_REPLY_PROB=0.0
    """
).strip() + "\n"


def ensure_env_file(path: Path = ENV_PATH) -> None:
    if path.exists():
        return
    print(f"[env] {path.name} 파일을 찾지 못해 기본 템플릿을 생성합니다.")
    path.write_text(DEFAULT_ENV_TEMPLATE, encoding="utf-8")
