print("Initializing bot...")
import os
import random
import time
from typing import Set
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent
print("Loading libraries...")
from aiogram import Bot, Dispatcher, Router, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from dotenv import load_dotenv
print("Loading modules...")
import commands
import llm
import post_idle
from chat_filters import ChatAllowed, parse_ids_from_env
from store import init_db, save_message
from setenv import ensure_env_file

# 기본 설정

print("Loading environment variables...")
ensure_env_file()
init_db()
load_dotenv(BASE_DIR / ".env")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("환경변수 TELEGRAM_BOT_TOKEN이 설정되어 있지 않습니다. .env 파일을 확인하세요.")

CALL_KEYWORDS = ("히시 미라클", "히시미라클", "미라코")

def _parse_idle_reply_probability(env_name: str = "BOT_IDLE_REPLY_PROB") -> float:
    raw = os.getenv(env_name)
    if not raw:
        return 0.0
    try:
        value = float(raw)
    except ValueError:
        print(f"[warn] {env_name} 값이 올바르지 않아요: {raw!r}. 0으로 처리할게요.")
        return 0.0
    return max(0.0, min(1.0, value))

IDLE_REPLY_PROBABILITY = _parse_idle_reply_probability()

ALLOWED_CHAT_IDS: Set[int] = parse_ids_from_env("TELEGRAM_GROUP_IDS")
# print("ALLOWED (raw):", os.getenv("TELEGRAM_GROUP_IDS"))
# print("ALLOWED (parsed):", ALLOWED_CHAT_IDS)

# 관리자 권한

print("Setting up admin users...")
def _parse_admin_ids(raw: str | None) -> set[int]:
    if not raw:
        return set()

    admin_ids: set[int] = set()
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            admin_ids.add(int(chunk))
        except ValueError:
            print(f"[warning] TELEGRAM_ADMIN_IDS에 잘못된 값이 있어요: {chunk}")
    return admin_ids


ADMIN_IDS = _parse_admin_ids(os.getenv("TELEGRAM_ADMIN_IDS"))



def is_admin(user_id: int | None) -> bool:
    """TELEGRAM_ADMIN_IDS가 비어 있으면 모든 사용자 허용."""
    if not ADMIN_IDS:
        return True
    return user_id is not None and user_id in ADMIN_IDS



# 봇 인스턴스

print("Starting bot")
bot = Bot(
    token=TELEGRAM_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()


# 채팅방 필터링

router = Router()
chat_filter = ChatAllowed(ALLOWED_CHAT_IDS, notify=True, notice="트레이너가 모르는 사람이랑 말하지 말래요...")
router.message.filter(chat_filter)
router.callback_query.filter(chat_filter)
router.chat_member.filter(chat_filter)
router.my_chat_member.filter(chat_filter)
dp.include_router(router)


# 봇 명령어

command_list = ["umastart", "umabot", "umahumor"]

@router.message(Command(commands=command_list))
async def handle_commands(msg: types.Message):
    """Delegate command handling to the commands module."""
    await commands.handle_command(
        msg=msg,
        bot=bot,
        is_admin=is_admin,
        allowed_chat_ids=ALLOWED_CHAT_IDS,
    )



# 일반 메시지 처리

@router.message()
async def on_message(msg: types.Message):
    print(f"{msg.from_user.username}: {msg.text}")

    if msg.text and msg.text.startswith("/"):
        return

    me = await bot.get_me()

    if msg.text and f"@{me.username}" in msg.text:
        question = msg.text.replace(f"@{me.username}", "").strip()
    else:
        question = msg.text

    if msg.text:
        save_message(
            msg.chat.id,
            msg.from_user.id,
            msg.from_user.username,
            'user',
            question,
            int(time.time())
        )

    # 응답 트리거 체크

    triggered = False
    if msg.text and f"@{me.username}" in msg.text:
        triggered = True
    if msg.reply_to_message and msg.reply_to_message.from_user and msg.reply_to_message.from_user.id == me.id:
        triggered = True
    if msg.text and any(keyword in msg.text for keyword in CALL_KEYWORDS):
        triggered = True
    if not triggered and question and IDLE_REPLY_PROBABILITY > 0:
        roll = random.random()
        if roll < IDLE_REPLY_PROBABILITY:
            triggered = True
            print(f"[bot] idle trigger fired (p={IDLE_REPLY_PROBABILITY}, roll={roll:.3f})")
    if not triggered:
        return


    # LLM 호출 및 응답

    response_text = llm.generate_genai(
        chat_id=msg.chat.id,
        user_name=msg.from_user.username,
        user_msg=question
    )
    if not response_text:
        response_text = "미라클이 잠시 생각에 잠겼어요... 조금 있다가 다시 시도해 주세요."
    await msg.answer(response_text)

    # 봇 메시지 저장

    save_message(
        msg.chat.id,
        None,
        'Miracle',
        'bot',
        response_text,
        int(time.time())
    )

async def run_bot():
    idle_poster = post_idle.start_idle_task(bot, ALLOWED_CHAT_IDS)
    try:
        await dp.start_polling(bot)
    finally:
        if idle_poster:
            await idle_poster.stop()


if __name__ == "__main__":
    import asyncio

    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        print("\n[bot] 중단 신호를 받아 안전하게 종료했어요.\n")



