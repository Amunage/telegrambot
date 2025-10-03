"""SQLite-backed persistence helpers for the Telegram bot."""

import os
import sqlite3
import time
from typing import Any, List, Optional, Tuple

import utils


### 기본 경로 / 상수

DB_PATH = os.path.join(utils.mainpath, "chat.db")
CHAT_DB_PATH = os.getenv("CHAT_DB_PATH", "chat.db")



### 내부 헬퍼

def get_conn() -> sqlite3.Connection:
    """공통 PRAGMA가 적용된 데이터베이스 커넥션을 생성합니다."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _rowcount(cursor: sqlite3.Cursor) -> int:
    """sqlite3에서 rowcount가 -1일 수 있는 문제를 보완합니다."""
    try:
        return cursor.rowcount if cursor.rowcount is not None else 0
    except Exception:
        return 0



### 스키마 초기화 / 마이그레이션

def init_db() -> None:
    """필요한 모든 테이블과 누락된 컬럼을 생성합니다."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_conn()
    try:
        c = conn.cursor()

        # 메시지 테이블
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS messages(
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id  INTEGER NOT NULL,
                user_id  INTEGER,
                username TEXT,
                sender   TEXT,
                text     TEXT,
                ts       INTEGER
            )
            """
        )

        c.execute("PRAGMA table_info(messages)")
        message_columns = {row[1] for row in c.fetchall()}
        if "sender" not in message_columns:
            c.execute("ALTER TABLE messages ADD COLUMN sender TEXT")
            c.execute(
                """
                UPDATE messages
                   SET sender = CASE
                     WHEN user_id IS NULL THEN 'bot'
                     ELSE 'user'
                   END
                """
            )

        # 설정 테이블 (기본값 포함)

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS settings(
                chat_id        INTEGER PRIMARY KEY,
                persona        TEXT DEFAULT 'seiunsky',
                style          TEXT DEFAULT 'jondae',
                window_minutes INTEGER DEFAULT 60,
                memory_limit   INTEGER DEFAULT 10,
                keep_per_chat  INTEGER DEFAULT 100,
                retain_days    INTEGER DEFAULT 3
            )
            """
        )

        for col, decl in [
            ("persona", "TEXT DEFAULT 'seiunsky'"),
            ("style", "TEXT DEFAULT 'jondae'"),
            ("window_minutes", "INTEGER DEFAULT 60"),
            ("memory_limit", "INTEGER DEFAULT 10"),
            ("keep_per_chat", "INTEGER DEFAULT 100"),
            ("retain_days", "INTEGER DEFAULT 3"),
        ]:
            try:
                c.execute(f"ALTER TABLE settings ADD COLUMN {col} {decl}")
            except sqlite3.OperationalError:
                pass

        # 커스텀 지침 테이블

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS guidelines(
                chat_id    INTEGER PRIMARY KEY,
                guidetext  TEXT,
                updated_by INTEGER,
                updated_at INTEGER
            )
            """
        )

        c.execute("PRAGMA table_info(guidelines)")
        guideline_columns = {row[1] for row in c.fetchall()}
        if "updated_by" not in guideline_columns:
            c.execute("ALTER TABLE guidelines ADD COLUMN updated_by INTEGER")
        if "updated_at" not in guideline_columns:
            c.execute("ALTER TABLE guidelines ADD COLUMN updated_at INTEGER")

        c.execute(
            """CREATE INDEX IF NOT EXISTS idx_messages_chat_ts
                   ON messages(chat_id, ts)"""
        )

        conn.commit()
    finally:
        conn.close()


def _ensure_settings_row(chat_id: int) -> None:
    """settings 테이블에 해당 chat_id 행이 없으면 생성합니다."""
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("SELECT chat_id FROM settings WHERE chat_id=?", (chat_id,))
        if not c.fetchone():
            c.execute("INSERT INTO settings(chat_id) VALUES(?)", (chat_id,))
            conn.commit()
    finally:
        conn.close()


### CHAT_DB 없으면 생성

_db_dir = os.path.dirname(CHAT_DB_PATH)
if _db_dir and not os.path.exists(_db_dir):
    os.makedirs(_db_dir, exist_ok=True)
    init_db()



### 메시지 저장 / 조회

def save_message(
    chat_id: int,
    user_id: Optional[int],
    username: Optional[str],
    sender: str,
    text: str,
    ts: Optional[int] = None,
) -> None:
    """대화 메시지를 저장합니다. sender는 'user' 또는 'bot'."""
    ts = ts or int(time.time())
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(
            """INSERT INTO messages(chat_id, user_id, username, sender, text, ts)
                   VALUES(?,?,?,?,?,?)""",
            (chat_id, user_id, username, sender, text, ts),
        )
        conn.commit()
    finally:
        conn.close()


def get_recent_messages(chat_id: int, minutes: int, limit: int) -> List[Tuple[int, str, str, int]]:
    """최근 N분 간의 메시지를 오래된 순서로 최대 limit개 반환합니다."""
    now = int(time.time())
    since = now - minutes * 60
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(
            """SELECT user_id, COALESCE(username, sender) AS name, text, ts
                   FROM messages
                  WHERE chat_id=? AND ts>=?
                  ORDER BY ts DESC, id DESC
                  LIMIT ?""",
            (chat_id, since, limit),
        )
        rows = list(reversed(c.fetchall()))
    finally:
        conn.close()
    return rows


def get_messages_before(chat_id: int, before_ts: int, limit: int = 200) -> List[Tuple[int, str, str, int]]:
    """특정 타임스탬프 이전의 메시지를 오래된 순서로 반환합니다."""
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(
            """SELECT user_id, COALESCE(username, sender) AS name, text, ts
                   FROM messages
                  WHERE chat_id=? AND ts<?
                  ORDER BY ts DESC
                  LIMIT ?""",
            (chat_id, before_ts, limit),
        )
        rows = list(reversed(c.fetchall()))
    finally:
        conn.close()
    return rows


def get_last_message(chat_id: int) -> Optional[Tuple[str, str, int]]:
    """가장 최근 메시지의 (sender, text, ts) 정보를 반환합니다."""
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(
            """SELECT sender, text, ts
                   FROM messages
                  WHERE chat_id=?
                  ORDER BY ts DESC, id DESC
                  LIMIT 1""",
            (chat_id,),
        )
        row = c.fetchone()
    finally:
        conn.close()

    if not row:
        return None
    sender = row[0] or ""
    text = row[1] or ""
    ts = int(row[2]) if row[2] else 0
    return sender, text, ts



### 컨텍스트 설정 (commands.py 연동)

def get_memory_config(chat_id: int) -> Tuple[int, int, int, int]:
    _ensure_settings_row(chat_id)
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute(
            """SELECT window_minutes, memory_limit, keep_per_chat, retain_days
                   FROM settings WHERE chat_id=?""",
            (chat_id,),
        )
        row = c.fetchone()
    finally:
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
) -> None:
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
    try:
        c = conn.cursor()
        c.execute(f"UPDATE settings SET {', '.join(fields)} WHERE chat_id=?", vals)
        conn.commit()
    finally:
        conn.close()



### 커스텀 지침 정책

def set_guidelines(chat_id: int, text: str, updated_by: int | None = None) -> None:
    """방별 커스텀 지침을 저장하거나 빈 문자열이면 삭제합니다."""
    conn = get_conn()
    try:
        c = conn.cursor()
        now = int(time.time())
        if text.strip():
            c.execute(
                """
                INSERT INTO guidelines(chat_id, guidetext, updated_by, updated_at)
                VALUES(?,?,?,?)
                ON CONFLICT(chat_id) DO UPDATE SET guidetext=excluded.guidetext,
                                                  updated_by=excluded.updated_by,
                                                  updated_at=excluded.updated_at
                """,
                (chat_id, text, updated_by, now),
            )
        else:
            c.execute("DELETE FROM guidelines WHERE chat_id=?", (chat_id,))
        conn.commit()
    finally:
        conn.close()


def get_guidelines(chat_id: int) -> str:
    """방별 커스텀 지침 텍스트를 반환합니다 (없으면 빈 문자열)."""
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("SELECT guidetext FROM guidelines WHERE chat_id=?", (chat_id,))
        row = c.fetchone()
    finally:
        conn.close()
    return row[0] if row and row[0] else ""


def clear_guidelines(chat_id: int) -> None:
    """특정 방의 커스텀 지침을 삭제합니다."""
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM guidelines WHERE chat_id=?", (chat_id,))
        conn.commit()
    finally:
        conn.close()



### 정리/보존 정책 (commands.py의 cleanup 명령과 연동)

def cleanup_keep_recent_per_chat(keep: int) -> int:
    """각 채팅방의 최근 keep개 메시지만 남기고 나머지를 삭제합니다."""
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("SELECT DISTINCT chat_id FROM messages")
        chat_ids = [row[0] for row in c.fetchall()]
        deleted_total = 0

        for cid in chat_ids:
            c.execute(
                """
                DELETE FROM messages
                 WHERE id IN (
                       SELECT id FROM messages
                        WHERE chat_id=?
                        ORDER BY ts DESC, id DESC
                        LIMIT -1 OFFSET ?
                 )
                """,
                (cid, keep),
            )
            deleted_total += _rowcount(c)

        conn.commit()
    finally:
        conn.close()
    return deleted_total


def cleanup_old_messages(days: int) -> int:
    """days일보다 오래된 메시지를 삭제합니다 (0이면 전체 삭제)."""
    conn = get_conn()
    try:
        c = conn.cursor()
        if days <= 0:
            c.execute("DELETE FROM messages")
            deleted = _rowcount(c)
            conn.commit()
            return deleted

        cutoff = int(time.time()) - days * 86400
        c.execute("DELETE FROM messages WHERE ts < ?", (cutoff,))
        deleted = _rowcount(c)
        conn.commit()
        return deleted
    finally:
        conn.close()



### 유지보수

def vacuum() -> None:
    """VACUUM 명령으로 DB 파일을 최적화합니다."""
    conn = get_conn()
    try:
        conn.execute("VACUUM")
    finally:
        conn.close()


def reset_db() -> None:
    """모든 데이터를 삭제하고 스키마를 재생성합니다."""
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("DROP TABLE IF EXISTS messages")
        c.execute("DROP TABLE IF EXISTS settings")
        c.execute("DROP TABLE IF EXISTS guidelines")
        conn.commit()
    finally:
        conn.close()

    # 파일 파편 정리 후 스키마 재생성
    vacuum_conn = sqlite3.connect(DB_PATH)
    try:
        vacuum_conn.execute("VACUUM")
        vacuum_conn.commit()
    finally:
        vacuum_conn.close()

    init_db()