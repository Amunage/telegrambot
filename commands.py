import time
from typing import Callable, Set

from aiogram import Bot, types

import post_idle
from context_builder import build_context_for_llm
from quota import (
    get_limits,
    get_usage_summary_today,
    reset_limits,
    reset_usage,
    set_limit,
)
from store import (
    cleanup_keep_recent_per_chat,
    cleanup_old_messages,
    clear_guidelines,
    get_guidelines,
    get_memory_config,
    reset_db,
    save_message,
    set_guidelines,
    set_memory_config,
)
from persona import bot_name
BOT_NAME = bot_name


HELP_TEXT = (
    "[설정]\n"
    "memory show - 메모리 설정 보기\n"
    "memory set [TIME] [COUNT] - 메모리 설정 변경\n"
    "memory retain [COUNT] [DAY] - 총 보존 개수·일수 설정\n"
    "---\n"
    "guide show - 커스텀 지침 보기\n"
    "guide set [TEXT] - 커스텀 지침 설정/덮어쓰기\n"
    "guide clear - 커스텀 지침 삭제\n"
    "---\n"
    "quota show - 오늘 사용량/현재 한도 보기\n"
    "quota set [KEY] [INT] - 한도 변경 (세션/DB 오버라이드)\n"
    "quota reset [limits|today|all] - 한도/사용량 초기화\n"
    "---\n"
    "data context - 현재 컨텍스트 미리보기\n"
    "data reset - 모든 데이터 초기화"
)


def bot_settings(parts, chat_id, user_id, user_name):
    if len(parts) < 2:
        return HELP_TEXT

    command = parts[1].lower()
    if command == "help":
        return HELP_TEXT

    if command == "memory":
        win, lim, keep, days = get_memory_config(chat_id)

        if len(parts) < 3:
            return "[사용법] /botset memory [show|set|retain]"

        sub = parts[2].lower()

        if sub == "show":
            return f"[메모리] 최근 {win}분, 최대 {lim}개\n보존: 채팅방별 최근 {keep}개, {days}일 보관"

        if sub == "set":
            if len(parts) < 5:
                return "[사용법] /botset memory set [분] [개수]  예) /botset memory set 60 100"
            try:
                win = max(1, int(parts[3]))
                lim = max(1, int(parts[4]))
            except ValueError:
                return "[사용법] /botset memory set [분] [개수]  예) /botset memory set 60 100"
            set_memory_config(chat_id, window_minutes=win, memory_limit=lim)
            return f"[컨텍스트 설정 완료] 최근 {win}분, 최대 {lim}개"

        if sub == "retain":
            if len(parts) < 5:
                return "[사용법] /botset memory retain [개수] [일수]  예) /botset memory retain 3000 3"
            try:
                n = max(100, int(parts[3]))
                m = max(1, int(parts[4]))
            except ValueError:
                return "[사용법] /botset memory retain [개수] [일수]  예) /botset memory retain 3000 3"
            set_memory_config(chat_id, keep_per_chat=n, retain_days=m)
            deleted1 = cleanup_keep_recent_per_chat(keep=n)
            deleted2 = cleanup_old_messages(days=m)
            return f"[보존 설정 완료] 채팅방별 최근 {n}개, {m}일 보관 (대략 {deleted1} + {deleted2}개 정리)"

        return "[사용법] /botset memory [show|set|retain]"

    if command == "guide":
        if len(parts) < 3:
            return "[사용법] /botset guide [show|set|clear]"

        sub = parts[2].lower()

        if sub == "show":
            txt = get_guidelines(chat_id)
            if not txt.strip():
                return "현재 커스텀 지침이 없어요."
            preview = (txt[:900] + "…") if len(txt) > 900 else txt
            return f"커스텀 지침\n<pre>{preview}</pre>"

        if sub == "set":
            if len(parts) < 4:
                return "[사용법] /botset guide set [지침내용]"
            text = " ".join(parts[3:]).strip()
            set_guidelines(chat_id, text, updated_by=user_id)
            return f"커스텀 지침을 저장했어요. ({len(text)}자)"

        if sub == "clear":
            clear_guidelines(chat_id)
            return "커스텀 지침을 삭제했어요."

        return "[사용법] /botset guide [show|set|clear]"

    if command == "quota":
        if len(parts) < 3:
            return "[사용법] /botset quota [show|set|reset]"
        sub = parts[2].lower()

        if sub == "show":
            limits = get_limits()
            us = get_usage_summary_today()
            tc, ti, to = us["total"]
            return f"오늘 사용량(총)\n- 호출: {tc}\n- 입력 문자: {ti}\n- 출력 토큰(추정): {to}"

        if sub == "set":
            if len(parts) < 5:
                keys = (
                    "MAX_CALLS_PER_DAY | MAX_INPUT_CHARS_PER_DAY | "
                    "MAX_OUTPUT_TOKENS_PER_DAY | MAX_CALLS_PER_CHAT_PER_DAY"
                )
                return f"[사용법] /botset quota set <KEY> <값>\n가능키: {keys}"
            key = parts[3].upper()
            try:
                value = int(parts[4])
            except ValueError:
                return "값은 정수여야 해요."
            try:
                set_limit(key, value)
            except ValueError as e:
                return f"오류: {e}"
            return f"{key} = {value} 로 설정했어요."

        if sub == "reset":
            scope = parts[3].lower() if len(parts) >= 4 else "limits"
            if scope == "limits":
                reset_limits()
                return "한도 오버라이드를 초기화했어요."
            if scope in ("today", "all"):
                reset_usage(scope)
                return f"사용량을 초기화했어요. (scope={scope})"
            return "[사용법] /botset quota reset [limits|today|all]"

        return "[사용법] /botset quota [show|set|reset]"

    if command == "data":
        if len(parts) < 3:
            return "[사용법] /botset data [context|reset]"
        sub = parts[2].lower()
        if sub == "reset":
            reset_db()
            return "DB 스키마를 초기화했어요. (모든 데이터 삭제)"

        if sub == "context":
            try:
                final_ctx = build_context_for_llm(
                    chat_id=chat_id,
                    user_name=user_name,
                    user_msg="메세지",
                    budget_chars=3000,
                )
            except Exception as err:
                print(f"[ctx] build_context_for_llm error: {err}")
                return "컨텍스트 생성 중 오류가 발생했어요. 로그를 확인해 주세요."

            if not final_ctx.strip():
                return "컨텍스트가 비어있어요. 최근 대화가 있는지 확인해 주세요."

            return f"<pre>{final_ctx}</pre>"

        return "[사용법] /botset data [context|reset]"

    return "모르겠어요. /botset help 로 도움말을 확인하세요."


async def handle_command(
    msg: types.Message,
    bot: Bot,
    is_admin: Callable[[int | None], bool],
    allowed_chat_ids: Set[int] | None = None,
) -> None:
    if not is_admin(msg.from_user.id if msg.from_user else None):
        await msg.answer("이 명령은 관리자만 사용할 수 있어요.")
        return

    command = (msg.text or "").split(maxsplit=1)[0].lower().lstrip("/")

    if command == "botstart":
        if allowed_chat_ids is not None:
            print(f"[info] {msg.chat.id} / {allowed_chat_ids}")
        else:
            print(f"[info] {msg.chat.id}")
        await msg.answer("안녕하세요.")
        return

    if command == "botset":
        print(f'{msg.from_user.id}: {msg.text}')
        parts = (msg.text or "").split()
        chat_id = msg.chat.id
        user_id = msg.from_user.id if msg.from_user else None
        user_name = msg.from_user.username if msg.from_user else None

        text = bot_settings(parts, chat_id, user_id, user_name)
        if text:
            await msg.answer(text)
        return

    if command == "botpost":
        post_text = await post_idle.fetch_post_message(bot)
        if not post_text:
            await msg.answer("지금은 포스트를 가져오지 못했어요. 잠시 후 다시 시도해 주세요!")
            return

        await msg.answer(post_text)

        save_message(
            msg.chat.id,
            None,
            BOT_NAME,
            'bot',
            post_text,
            int(time.time())
        )
        return

    await msg.answer("사용할 수 있는 명령이 아니에요.")
