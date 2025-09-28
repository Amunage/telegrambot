# store.py
import sqlite3
import time
from typing import List, Tuple, Optional, Any

import os
import utils

DB_PATH = os.path.join(utils.mainpath, "chat.db")

# =========================
# 내부 헬퍼
# =========================
def get_conn():
    """
    공통 PRAGMA 적용 커넥션
    - WAL: 동시 읽기/쓰기 안정화
    - foreign_keys: 일관성
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def _rowcount(cursor: sqlite3.Cursor) -> int:
    # sqlite3는 rowcount가 -1일 수 있으므로 보호
    try:
        return cursor.rowcount if cursor.rowcount is not None else 0
    except Exception:
        return 0

# =========================
# 스키마 초기화 / 마이그레이션
# =========================
def init_db():
    """
    messages, settings 테이블 생성 및 누락 컬럼 추가.
    - settings 컬럼:
        persona TEXT, style TEXT,
        window_minutes INTEGER, memory_limit INTEGER,
        keep_per_chat INTEGER, retain_days INTEGER
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_conn()
    c = conn.cursor()

    # 메시지 테이블
    c.execute("""
    CREATE TABLE IF NOT EXISTS messages(
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id  INTEGER NOT NULL,
        user_id  INTEGER,
        username TEXT,
        sender   TEXT,
        text     TEXT,
        ts       INTEGER
    )
    """)

    c.execute("PRAGMA table_info(messages)")
    message_columns = {row[1] for row in c.fetchall()}
    if "sender" not in message_columns:
        c.execute("ALTER TABLE messages ADD COLUMN sender TEXT")
        c.execute(
            """UPDATE messages
                   SET sender = CASE
                     WHEN user_id IS NULL THEN 'bot'
                     ELSE 'user'
                   END
             """
        )

    # 설정 테이블 (기본값 포함)
    c.execute("""
    CREATE TABLE IF NOT EXISTS settings(
        chat_id        INTEGER PRIMARY KEY,
        persona        TEXT DEFAULT 'seiunsky',
        style          TEXT DEFAULT 'jondae',
        window_minutes INTEGER DEFAULT 60,
        memory_limit   INTEGER DEFAULT 10,
        keep_per_chat  INTEGER DEFAULT 100,
        retain_days    INTEGER DEFAULT 3
    )
    """)

    for col, decl in [
        ("persona",        "TEXT DEFAULT 'seiunsky'"),
        ("style",          "TEXT DEFAULT 'jondae'"),
        ("window_minutes", "INTEGER DEFAULT 60"),
        ("memory_limit",   "INTEGER DEFAULT 10"),
        ("keep_per_chat",  "INTEGER DEFAULT 100"),
        ("retain_days",    "INTEGER DEFAULT 3"),
    ]:
        try:
            c.execute(f"ALTER TABLE settings ADD COLUMN {col} {decl}")
        except sqlite3.OperationalError:
            pass

    # 커스텀 지침 테이블
    c.execute("""
    CREATE TABLE IF NOT EXISTS guidelines(
        chat_id    INTEGER PRIMARY KEY,
        guidetext  TEXT,
        updated_by INTEGER,
        updated_at INTEGER
    )
    """)

    c.execute("PRAGMA table_info(guidelines)")
    guideline_columns = {row[1] for row in c.fetchall()}
    if "updated_by" not in guideline_columns:
        c.execute("ALTER TABLE guidelines ADD COLUMN updated_by INTEGER")
    if "updated_at" not in guideline_columns:
        c.execute("ALTER TABLE guidelines ADD COLUMN updated_at INTEGER")

    c.execute("""CREATE INDEX IF NOT EXISTS idx_messages_chat_ts
                 ON messages(chat_id, ts)""")

    conn.commit()
    conn.close()

def _ensure_settings_row(chat_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT chat_id FROM settings WHERE chat_id=?", (chat_id,))
    if not c.fetchone():
        c.execute("INSERT INTO settings(chat_id) VALUES(?)", (chat_id,))
        conn.commit()
    conn.close()

# =========================
# 저장 / 조회
# =========================
def save_message(
    chat_id: int,
    user_id: Optional[int],
    username: Optional[str],
    sender: str,
    text: str,
    ts: Optional[int] = None
):
    """
    대화 메시지를 저장. sender: 'user' | 'bot'
    """
    ts = ts or int(time.time())
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """INSERT INTO messages(chat_id, user_id, username, sender, text, ts)
           VALUES(?,?,?,?,?,?)""",
        (chat_id, user_id, username, sender, text, ts)
    )
    conn.commit()
    conn.close()

def get_recent_messages(chat_id: int, minutes: int, limit: int) -> List[Tuple[int, str, str, int]]:
    """
    최근 N분/최대 M개 메시지를 '오래된→최신' 순서로 반환.
    반환 튜플: (user_id, name, text, ts)  ; name은 username가 없으면 sender 대체
    """
    now = int(time.time())
    since = now - minutes * 60
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """SELECT user_id, COALESCE(username, sender) AS name, text, ts
           FROM messages
           WHERE chat_id=? AND ts>=?
           ORDER BY ts DESC, id DESC
           LIMIT ?""",
        (chat_id, since, limit)
    )
    rows = list(reversed(c.fetchall()))
    conn.close()
    return rows

def get_messages_before(chat_id: int, before_ts: int, limit: int = 200) -> List[Tuple[int, str, str, int]]:
    """
    특정 시각 이전의 과거 메시지 일부를 '오래된→최신' 순서로 반환.
    recap 용도로 최신 가까운 것부터 limit개를 뽑아 뒤집는다.
    """
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """SELECT user_id, COALESCE(username, sender) AS name, text, ts
           FROM messages
           WHERE chat_id=? AND ts<?
           ORDER BY ts DESC
           LIMIT ?""",
        (chat_id, before_ts, limit)
    )
    rows = list(reversed(c.fetchall()))
    conn.close()
    return rows

# =========================
# 컨텍스트 설정 (settings.py 연동)
# =========================
def get_memory_config(chat_id: int) -> Tuple[int, int, int, int]:
    """
    settings.py가 기대하는 튜플 반환:
    (window_minutes, memory_limit, keep_per_chat, retain_days)
    """
    _ensure_settings_row(chat_id)
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """SELECT window_minutes, memory_limit, keep_per_chat, retain_days
           FROM settings WHERE chat_id=?""",
        (chat_id,)
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return (30, 16, 3000, 3)
    return tuple(int(x) for x in row)  # type: ignore

def set_memory_config(
    chat_id: int,
    *,
    window_minutes: Optional[int] = None,
    memory_limit: Optional[int] = None,
    keep_per_chat: Optional[int] = None,
    retain_days: Optional[int] = None,
    persona: Optional[str] = None,
    style: Optional[str] = None,
):
    """
    설정값을 부분 업데이트. None은 변경하지 않음.
    """
    _ensure_settings_row(chat_id)
    fields: List[str] = []
    vals: List[Any] = []
    for key, val in [
        ("window_minutes", window_minutes),
        ("memory_limit", memory_limit),
        ("keep_per_chat", keep_per_chat),
        ("retain_days", retain_days),
        ("persona", persona),
        ("style", style),
    ]:
        if val is not None:
            fields.append(f"{key}=?")
            vals.append(val)
    if not fields:
        return
    vals.append(chat_id)
    conn = get_conn()
    c = conn.cursor()
    c.execute(f"UPDATE settings SET {', '.join(fields)} WHERE chat_id=?", vals)
    conn.commit()
    conn.close()

# =========================
# 커스텀 지침 정책
# =========================

def set_guidelines(chat_id: int, text: str, updated_by: int|None=None):
    """방별 커스텀 지침 저장/갱신(덮어쓰기). 빈 문자열이면 삭제와 동일."""
    conn = get_conn(); c = conn.cursor()
    now = int(time.time())
    if text.strip():
        c.execute("""
            INSERT INTO guidelines(chat_id, guidetext, updated_by, updated_at)
            VALUES(?,?,?,?)
            ON CONFLICT(chat_id) DO UPDATE SET guidetext=excluded.guidetext,
                                              updated_by=excluded.updated_by,
                                              updated_at=excluded.updated_at
        """, (chat_id, text, updated_by, now))
    else:
        c.execute("DELETE FROM guidelines WHERE chat_id=?", (chat_id,))
    conn.commit(); conn.close()

def get_guidelines(chat_id: int) -> str:
    """방별 커스텀 지침 텍스트(없으면 빈 문자열)."""
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT guidetext FROM guidelines WHERE chat_id=?", (chat_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row and row[0] else ""

def clear_guidelines(chat_id: int):
    conn = get_conn(); c = conn.cursor()
    c.execute("DELETE FROM guidelines WHERE chat_id=?", (chat_id,))
    conn.commit(); conn.close()


# =========================
# 정리/보존 정책 (settings.py의 cleanup 명령이 호출)
# =========================
def cleanup_keep_recent_per_chat(keep: int) -> int:
    """
    모든 채팅방에 대해 '최근 keep개'만 남기고 나머지 삭제.
    대략적인 삭제 건수를 반환(정확치 않을 수 있음).
    """
    conn = get_conn()
    c = conn.cursor()

    # 각 chat_id별 id DESC 기준 keep offset 이후를 삭제
    # (sqlite는 윈도우 함수가 느릴 수 있어 서브쿼리 이용)
    c.execute("SELECT DISTINCT chat_id FROM messages")
    chat_ids = [row[0] for row in c.fetchall()]
    deleted_total = 0

    for cid in chat_ids:
        c.execute(
            """DELETE FROM messages
               WHERE id IN (
                 SELECT id FROM messages
                 WHERE chat_id=?
                 ORDER BY ts DESC, id DESC
                 LIMIT -1 OFFSET ?
               )""",
            (cid, keep)
        )
        deleted_total += _rowcount(c)

    conn.commit()
    conn.close()
    return deleted_total

def cleanup_old_messages(days: int) -> int:
    """
    days일보다 오래된 메시지 삭제.
    days=0 이면 전체 삭제.
    """
    conn = get_conn()
    c = conn.cursor()
    if days <= 0:
        c.execute("DELETE FROM messages")
        deleted = _rowcount(c)
        conn.commit()
        conn.close()
        return deleted

    cutoff = int(time.time()) - days * 86400
    c.execute("DELETE FROM messages WHERE ts < ?", (cutoff,))
    deleted = _rowcount(c)
    conn.commit()
    conn.close()
    return deleted

# =========================
# 유지보수
# =========================
def vacuum():
    """파일 조각/용량 정리를 위한 VACUUM (오프라인/저부하 시 사용 권장)"""
    conn = get_conn()
    conn.execute("VACUUM")
    conn.close()

def reset_db():
    """모든 데이터를 삭제하고 스키마를 재생성(강제)."""
    import os, sqlite3
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("DROP TABLE IF EXISTS messages")
        c.execute("DROP TABLE IF EXISTS settings")
        c.execute("DROP TABLE IF EXISTS guidelines")
        conn.commit()
    finally:
        conn.close()
    # 파일 파편 정리(선택)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("VACUUM")
        conn.commit()
    finally:
        conn.close()
    # 스키마 재생성
    init_db()