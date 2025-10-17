from typing import List

import store
import utils



def _clip(s:str, cap:int)->str:
    return s if len(s) <= cap else s[:cap-1] + "…"

def make_context_block(lines: List[str], max_chars:int)->str:
    buf=[]; used=0
    for ln in lines:
        s=ln.strip()
        if not s: continue
        if used + len(s) + 1 > max_chars: break
        buf.append(s); used += len(s) + 1
    return "\n".join(buf)

def build_context_for_llm(chat_id:int, user_name:str, user_msg:str, budget_chars:int=3000)->str:
    """
    [SYSTEM][MEMORY][RECAP][CHAT][USER] 순서로 조립한 최종 컨텍스트 반환.
    문자 기준 상한(budget_chars) 내에서 블록별 상한을 적용.
    """
    # --- 설정: settings.py가 기대하는 형태와 동일 ---
    # get_context_config -> (win_minutes, limit, keep_per_chat, retain_days)
    win, lim, _, _ = store.get_memory_config(chat_id)


    # --- GUIDELINES: 방별 커스텀 지침 ---
    guidelines = store.get_guidelines(chat_id).strip()
    guidelines_block = guidelines if guidelines else ""

    # --- CHAT: 최근창 ---
    rows = store.get_recent_messages(chat_id, minutes=win, limit=lim)
    chat_lines = utils.filter_and_compact(rows)
    chat_block = make_context_block(chat_lines, max_chars=int(budget_chars*0.6))

    # --- INPUT: 이번 입력 ---
    input_block = f"{user_name}: {user_msg}"

    # --- 조립 (블록별 상한) ---
    time_block = utils.korea_time()

    blocks = [
        ("[TIME]", time_block, 32),
        ("[GUIDELINES]", guidelines_block, 2000),
        ("[CHAT]",   chat_block,   int(budget_chars*0.6)),
        ("[INPUT]",   input_block,   800),
    ]

    buf=[]; total=0
    for tag, body, cap in blocks:
        piece = _clip(body, cap)
        add = len(tag) + len(piece) + 2
        if total + add > budget_chars:
            remain = max(0, budget_chars - total - len(tag) - 2)
            if remain > 0:
                piece = _clip(piece, remain)
                buf.append(f"{tag}\n{piece}")
                total += len(tag) + len(piece) + 2
            break
        buf.append(f"{tag}\n{piece}")
        total += add

    return "\n\n".join(buf)
