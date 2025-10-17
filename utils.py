from typing import List, Tuple
import os
import re
import time

mainpath = os.path.dirname(os.path.abspath(__file__))


def filter_and_compact(rows: List[Tuple[int, str, str, int]]) -> List[str]:
    """압축된 대화 로그를 생성한다.

    적용 정책
    - 길이/줄 수 제한: 최대 2줄, 50자 안팎으로 축약
    - 중복 제거: 같은 사용자가 직전에 올린 같은 내용은 무시
    - 노이즈 필터링: 링크, 이모지/특수문자만 있는 메시지 제거
    - 시간 정제: 너무 오래된 메시지는 제외
    """

    MAX_LENGTH = 110  # 최종 문자열 허용 길이
    CUT_LENGTH = 50  # 길이 초과 시 앞/뒤로 남길 문자 수
    MAX_AGE_SECONDS = 3 * 3600  # 시간 창(window) 밖 메시지 제거 (3시간)
    BANNED_STRINGS = {"…", "...", "으음", "글쎄요", "딱히"}  # 반복/헛기침 등 제거 대상 문자열
    now = time.time()

    out: List[str] = []
    last_message_by_user: dict[int, str] = {}

    for user_id, name, text, ts in rows:
        if not text:
            continue

        # 1) 시간 정제: 너무 오래된 메시지는 버림
        if ts and now - ts > MAX_AGE_SECONDS:
            continue

        raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not raw_lines:
            continue

        # 2) 중복 제거: 같은 사용자가 연속으로 남긴 동일 내용은 스킵
        base_joined = " ".join(raw_lines)
        base_normalized = re.sub(r"\s+", " ", base_joined).strip().lower()
        if last_message_by_user.get(user_id) == base_normalized:
            continue

        # 줄바꿈을 공백으로 합쳐 하나의 문장으로 만듦
        condensed = " ".join(raw_lines)

        # 명령어(`/start` 등)는 컨텍스트에 넣지 않음
        if condensed.startswith("/"):
            continue

        # URL은 컨텍스트에서 `url_link`로 치환하여 의미만 남김
        if re.search(r"https?://", condensed, flags=re.IGNORECASE):
            condensed = re.sub(r"https?://\S+", "<url_link>", condensed, flags=re.IGNORECASE)

        # 반복 문자는 2회까지만 남김 (ㅋㅋㅋㅋ → ㅋㅋ)
        condensed = re.sub(r"(.)\1{3,}", r"\1\1", condensed)

        # 공백 정규화
        condensed = re.sub(r"\s+", " ", condensed).strip()

        # 3) 노이즈 필터링: 의미 있는 문자(숫자/영문/한글/자모)가 없으면 버림
        alnum = re.sub(r"[^0-9A-Za-z가-힣ㄱ-ㅎㅏ-ㅣ]", "", condensed)
        if not alnum:
            continue

        # 상투적 문자열은 전체에서 제거
        for banned in BANNED_STRINGS:
            condensed = condensed.replace(banned, "")

        condensed = condensed.strip()

        if not condensed:
            continue

        normalized = condensed.lower()
        last_message_by_user[user_id] = normalized

        # 4) 길이 제한: 너무 긴 문장은 앞/뒤 일부만 남기고 축약
        if len(condensed) > MAX_LENGTH:
            condensed = condensed[:CUT_LENGTH] + " … " + condensed[-CUT_LENGTH:]

        # 실제 내용이 한 글자 이하라면 제외
        if len(condensed.replace(" ", "")) <= 1:
            continue

        out.append(f"{name or 'user'}: {condensed}")

    return out

def make_context_block(lines: List[str], max_chars:int)->str:
    buf=[]; used=0
    for ln in lines:
        s=ln.strip()
        if not s: continue
        if used + len(s) + 1 > max_chars: break
        buf.append(s); used += len(s) + 1
    return "\n".join(buf)
