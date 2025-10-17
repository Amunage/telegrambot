from __future__ import annotations

import asyncio
import random
import re
import time
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, Optional, Tuple
from urllib.parse import urljoin

import aiohttp
from aiogram import Bot
from bs4 import BeautifulSoup

import store
from persona import bot_name
BOT_NAME = bot_name

POST_NAME = "dogdrip"
POST_URL = "https://www.dogdrip.net/?mid=dogdrip&sort_index=popular"
POST_IDLE_MINUTES = 180  # 3 hours
POST_IDLE_CHECK_SECONDS = 600  # 최소 10분
POST_IDLE_HTTP_TIMEOUT = 10.0
POST_IDLE_MESSAGE_TEMPLATE = "{title}\n{link}"
POST_IDLE_QUIET_START_HOUR = 0  # 0시
POST_IDLE_QUIET_END_HOUR = 8    # 8시 미만까지 조용히
POST_IDLE_TIMEZONE = timezone(timedelta(hours=9))  # 한국 표준시
POST_BLOCKED_CHAT_IDS = {889998272} # 자동글 차단 예: 개인 채팅방


class IdlePOSTPoster:
    """채팅방이 일정 시간 이상 조용하면 포스트 링크를 전송하는 백그라운드 태스크."""

    def __init__(self, bot: Bot, chat_ids: Iterable[int]):
        self._bot = bot
        self._chat_ids = {cid for cid in chat_ids if cid}
        if POST_BLOCKED_CHAT_IDS:
            self._chat_ids.difference_update(POST_BLOCKED_CHAT_IDS)
        self._post_url = POST_URL
        self._idle_seconds = max(0, int(POST_IDLE_MINUTES * 60))
        self._check_interval = POST_IDLE_CHECK_SECONDS
        self._request_timeout = POST_IDLE_HTTP_TIMEOUT
        self._message_template = POST_IDLE_MESSAGE_TEMPLATE
        self._quiet_hours: Optional[Tuple[int, int]] = (
            POST_IDLE_QUIET_START_HOUR,
            POST_IDLE_QUIET_END_HOUR,
        )
        self._timezone = POST_IDLE_TIMEZONE

        self._last_post_marker: Dict[int, int] = {}
        self._recent_links: list[str] = []
        self._task: Optional[asyncio.Task[None]] = None

    @property
    def enabled(self) -> bool:
        if not self._chat_ids:
            print("[idle] 대상 채팅방이 없어 포스트 링크 자동 게시가 비활성화됩니다.")
            return False
        if self._idle_seconds <= 0:
            print("[idle] POST_IDLE_MINUTES가 0 이하로 설정되어 기능이 비활성화됩니다.")
            return False
        if not self._post_url:
            print("[idle] 사용할 포스트 주소가 설정되지 않아 기능이 비활성화됩니다.")
            return False
        return True

    def start(self) -> Optional[asyncio.Task[None]]:
        if not self.enabled:
            return None
        if self._task and not self._task.done():
            return self._task
        self._task = asyncio.create_task(self._run_loop(), name="idle-post-poster")
        return self._task

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run_loop(self) -> None:
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - 예방적 로그
                print(f"[idle] 배경 태스크 오류: {exc!r}")
            await asyncio.sleep(self._check_interval)

    async def _tick(self) -> None:
        now = int(time.time())
        if self._is_quiet_hours(now):
            return
        for chat_id in self._chat_ids:
            info = store.get_last_message(chat_id)
            if not info:
                continue
            _sender, _text, ts = info
            if ts <= 0:
                continue
            if now - ts < self._idle_seconds:
                continue

            marker = self._last_post_marker.get(chat_id)
            if marker is not None and now - marker < self._idle_seconds:
                continue

            article = await self._fetch_article()
            if not article:
                continue

            title, link = article
            message = self._format_message(title, link)

            try:
                await self._bot.send_message(chat_id, message)
            except Exception as exc:  # pragma: no cover - 네트워크/권한 오류 대비
                print(f"[idle] 메시지 전송 실패(chat={chat_id}): {exc!r}")
                continue

            sent_ts = int(time.time())
            POST_text = "[읽을거리] " + message
            store.save_message(
                chat_id,
                None,
                BOT_NAME,
                "bot",
                POST_text,
                sent_ts,
            )

            self._last_post_marker[chat_id] = sent_ts
            await asyncio.sleep(0.1)

    def _is_quiet_hours(self, epoch: Optional[int] = None) -> bool:
        if not self._quiet_hours:
            return False

        start, end = self._quiet_hours
        start = max(0, min(23, start))
        end = max(0, min(23, end))

        if start == end:
            return False

        tz = self._timezone or POST_IDLE_TIMEZONE
        target_epoch = epoch or time.time()
        hour = datetime.fromtimestamp(target_epoch, tz).hour

        if start < end:
            return start <= hour < end
        return hour >= start or hour < end

    async def _fetch_article(self) -> Optional[Tuple[str, str]]:
        timeout = aiohttp.ClientTimeout(total=self._request_timeout)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                text = await self._http_text(session, self._post_url)
        except Exception as exc:
            print(f"[idle] 포스트 페이지 요청 중 오류: {exc!r}")
            return None

        if not text:
            return None

        try:
            candidates = self._parse_post(text, base=self._post_url)
            if not candidates:
                return None
            return self._pick_candidate(candidates)
        except Exception as exc:
            print(f"[idle] 포스트 파싱 오류: {exc!r}")
            return None

    async def _http_text(self, session: aiohttp.ClientSession, url: str) -> Optional[str]:
        headers = {"User-Agent": "idle-post/1.0"}
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                print(f"[idle] 요청 실패(status={resp.status}, url={url})")
                return None
            return await resp.text()

    def _parse_post(self, html_text: str, base: str) -> list[Tuple[str, str]]:
        soup = BeautifulSoup(html_text, "html.parser")
        candidates: list[Tuple[str, str]] = []
        seen: set[str] = set()

        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            match = re.match(rf"^/{POST_NAME}/(\d+)$", href.split("?")[0])
            if not match:
                continue

            title = anchor.get_text(strip=True) or anchor.get("title", "").strip()
            if not title:
                continue

            absolute = urljoin(base, href)
            if absolute in seen:
                continue
            seen.add(absolute)
            candidates.append((title, absolute))
            if len(candidates) >= 30:
                break

        return candidates

    def _pick_candidate(self, candidates: list[Tuple[str, str]]) -> Tuple[str, str]:
        fresh = [item for item in candidates if item[1] not in self._recent_links]
        pool = fresh if fresh else candidates
        choice = random.choice(pool)

        link = choice[1]
        self._recent_links.append(link)
        if len(self._recent_links) > 10:
            self._recent_links.pop(0)

        return choice

    def _format_message(self, title: str, link: str) -> str:
        print(f"[idle] 준비된 포스트: {title} / {link}")
        message_title = "[포스트] "+ title
        try:
            return self._message_template.format(title=message_title, link=link)
        except Exception:
            return f"쉬는 동안 읽을거리 하나 드릴게요!\n{title}\n{link}"


def start_idle_task(bot: Bot, chat_ids: Iterable[int]) -> Optional[IdlePOSTPoster]:
    poster = IdlePOSTPoster(bot, chat_ids)
    task = poster.start()
    if not task:
        return None
    return poster


async def fetch_post_message(bot: Bot) -> Optional[str]:
    poster = IdlePOSTPoster(bot, [])
    article = await poster._fetch_article()
    if not article:
        return None
    title, link = article
    return poster._format_message(title, link)
