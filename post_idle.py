from __future__ import annotations

import asyncio
import random
import re
import time
from contextlib import suppress
from typing import Dict, Iterable, Optional, Tuple
from urllib.parse import urljoin

import aiohttp
from aiogram import Bot
from bs4 import BeautifulSoup

import store


DOGDRIP_POPULAR_URL = "https://www.dogdrip.net/?mid=dogdrip&sort_index=popular"
HUMOR_IDLE_MINUTES = 180  # 3 hours
HUMOR_IDLE_CHECK_SECONDS = 300  # 최소 30초
HUMOR_IDLE_HTTP_TIMEOUT = 10.0
HUMOR_IDLE_MESSAGE_TEMPLATE = "{title}\n{link}"


class IdleHumorPoster:
    """채팅방이 일정 시간 이상 조용하면 도그드립 인기글 링크를 전송하는 백그라운드 태스크."""

    def __init__(self, bot: Bot, chat_ids: Iterable[int]):
        self._bot = bot
        self._chat_ids = {cid for cid in chat_ids if cid}
        self._dogdrip_url = DOGDRIP_POPULAR_URL
        self._idle_seconds = max(0, int(HUMOR_IDLE_MINUTES * 60))
        self._check_interval = HUMOR_IDLE_CHECK_SECONDS
        self._request_timeout = HUMOR_IDLE_HTTP_TIMEOUT
        self._message_template = HUMOR_IDLE_MESSAGE_TEMPLATE

        self._last_post_marker: Dict[int, int] = {}
        self._recent_links: list[str] = []
        self._task: Optional[asyncio.Task[None]] = None

    @property
    def enabled(self) -> bool:
        if not self._chat_ids:
            print("[idle] 대상 채팅방이 없어 유머 링크 자동 게시가 비활성화됩니다.")
            return False
        if self._idle_seconds <= 0:
            print("[idle] HUMOR_IDLE_MINUTES가 0 이하로 설정되어 기능이 비활성화됩니다.")
            return False
        if not self._dogdrip_url:
            print("[idle] 사용할 도그드립 주소가 설정되지 않아 기능이 비활성화됩니다.")
            return False
        return True

    def start(self) -> Optional[asyncio.Task[None]]:
        if not self.enabled:
            return None
        if self._task and not self._task.done():
            return self._task
        self._task = asyncio.create_task(self._run_loop(), name="idle-humor-poster")
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
            if marker is not None and marker >= ts:
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
            store.save_message(
                chat_id,
                None,
                "Miracle",
                "bot",
                message,
                sent_ts,
            )

            self._last_post_marker[chat_id] = sent_ts
            await asyncio.sleep(0.1)

    async def _fetch_article(self) -> Optional[Tuple[str, str]]:
        timeout = aiohttp.ClientTimeout(total=self._request_timeout)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                text = await self._http_text(session, self._dogdrip_url)
        except Exception as exc:
            print(f"[idle] 도그드립 페이지 요청 중 오류: {exc!r}")
            return None

        if not text:
            return None

        try:
            candidates = self._parse_dogdrip_popular(text, base=self._dogdrip_url)
            if not candidates:
                return None
            return self._pick_candidate(candidates)
        except Exception as exc:
            print(f"[idle] 도그드립 파싱 오류: {exc!r}")
            return None

    async def _http_text(self, session: aiohttp.ClientSession, url: str) -> Optional[str]:
        headers = {"User-Agent": "idle-humor/1.0"}
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                print(f"[idle] 요청 실패(status={resp.status}, url={url})")
                return None
            return await resp.text()

    def _parse_dogdrip_popular(self, html_text: str, base: str) -> list[Tuple[str, str]]:
        soup = BeautifulSoup(html_text, "html.parser")
        candidates: list[Tuple[str, str]] = []
        seen: set[str] = set()

        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            match = re.match(r"^/dogdrip/(\d+)$", href.split("?")[0])
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
        try:
            return self._message_template.format(title=title, link=link)
        except Exception:
            return f"쉬는 동안 읽을거리 하나 드릴게요!\n{title}\n{link}"


def start_idle_task(bot: Bot, chat_ids: Iterable[int]) -> Optional[IdleHumorPoster]:
    poster = IdleHumorPoster(bot, chat_ids)
    task = poster.start()
    if not task:
        return None
    return poster


async def fetch_humor_message(bot: Bot) -> Optional[str]:
    poster = IdleHumorPoster(bot, [])
    article = await poster._fetch_article()
    if not article:
        return None
    title, link = article
    return poster._format_message(title, link)
