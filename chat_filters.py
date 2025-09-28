from __future__ import annotations
import os
from typing import Set, Optional
from aiogram import types, Bot
from aiogram.filters import Filter


def parse_ids_from_env(var_name: str = "TELEGRAM_GROUP_IDS") -> Set[int]:
    """
    예: TELEGRAM_GROUP_IDS="-4716105514, 123456789"
    공백/빈값/잘못된 값은 건너뜀.
    """
    raw = os.getenv(var_name, "") or ""
    out: Set[int] = set()
    for chunk in raw.replace(" ", "").split(","):
        if not chunk:
            continue
        try:
            out.add(int(chunk))
        except ValueError:
            print(f"[warn] Ignore invalid chat id in {var_name}: {chunk!r}")
    return out


class ChatAllowed(Filter):
    """
    허용된 chat.id 인지 검사하는 필터.
    notify=True 이면 차단시 안내 메시지를 보냄.
    """
    def __init__(
        self,
        allowed_ids: Optional[Set[int]] = None,
        *,
        notify: bool = False,
        notice: str = "이 채팅방은 허용 목록에 없습니다."
    ):
        self.allowed_ids = allowed_ids or set()
        self.notify = notify
        self.notice = notice

        self.blocked = False

    async def __call__(self, event: types.TelegramObject, bot: Bot) -> bool:
        chat = None
        if isinstance(event, types.Message):
            chat = event.chat
        elif isinstance(event, types.CallbackQuery) and event.message:
            chat = event.message.chat
        elif isinstance(event, types.ChatMemberUpdated):
            chat = event.chat

        # chat이 없으면(인라인/특수 이벤트) 기본 차단
        if not chat:
            # 콜백쿼리는 alert로 간단 안내 가능
            if self.notify and isinstance(event, types.CallbackQuery):
                try:
                    await event.answer("여기서는 사용할 수 없어요.", show_alert=True)
                except Exception:
                    pass
            return False

        # 허용이면 통과
        if chat.id in self.allowed_ids:
            return True

        # 차단 안내 (무한루프 방지: 봇 메시지에는 알림 X)
        if self.notify:
            print(f"[info] {chat.id} / {self.allowed_ids})")
            try:
                if isinstance(event, types.Message):
                    if not self.blocked:
                        await bot.send_message(chat.id, self.notice)
                        self.blocked = True
                elif isinstance(event, types.CallbackQuery):
                    await event.answer("이 채팅방에서는 사용할 수 없어요.", show_alert=True)
                else:
                    # 그 외 타입은 조용히 무시
                    pass
            except Exception:
                pass

        return False
