from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Tuple


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


USAGE_DB_PATH = os.getenv("USAGE_DB_PATH", "usage.db")

# DB 파일의 디렉토리가 존재하지 않으면 생성
_db_dir = os.path.dirname(USAGE_DB_PATH)
if _db_dir and not os.path.exists(_db_dir):
    os.makedirs(_db_dir, exist_ok=True)

# Defaults pulled once at import; they can be overridden via DB entries.
_ENV_LIMITS: Dict[str, int] = {
    "MAX_CALLS_PER_DAY": _env_int("MAX_CALLS_PER_DAY", 100),
    "MAX_INPUT_CHARS_PER_DAY": _env_int("MAX_INPUT_CHARS_PER_DAY", 100_000),
    "MAX_OUTPUT_TOKENS_PER_DAY": _env_int("MAX_OUTPUT_TOKENS_PER_DAY", 20_000),
    "MAX_CALLS_PER_CHAT_PER_DAY": _env_int("MAX_CALLS_PER_CHAT_PER_DAY", 0),
}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _initialise_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS usage_daily(
          day TEXT NOT NULL,
          chat_id INTEGER NOT NULL,
          calls INTEGER DEFAULT 0,
          input_chars INTEGER DEFAULT 0,
          output_tokens INTEGER DEFAULT 0,
          PRIMARY KEY(day, chat_id)
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS usage_daily_total(
          day TEXT PRIMARY KEY,
          calls INTEGER DEFAULT 0,
          input_chars INTEGER DEFAULT 0,
          output_tokens INTEGER DEFAULT 0
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS quota_limits(
          key TEXT PRIMARY KEY,
          value INTEGER NOT NULL
        )
        """
    )


def _with_conn(fn: Callable[..., Any]) -> Callable[..., Any]:
    def wrap(*args, **kwargs):
        conn = sqlite3.connect(USAGE_DB_PATH)
        try:
            _initialise_schema(conn)
            return fn(conn, *args, **kwargs)
        finally:
            conn.close()

    return wrap


@_with_conn
def _get_overrides(conn: sqlite3.Connection) -> Dict[str, int]:
    rows = conn.execute("SELECT key, value FROM quota_limits").fetchall()
    return {key: int(value) for key, value in rows}


def get_limits() -> Dict[str, int]:
    """Return the effective limits (environment defaults merged with overrides)."""
    effective = dict(_ENV_LIMITS)
    effective.update(_get_overrides())
    return effective


@_with_conn
def set_limit(conn: sqlite3.Connection, key: str, value: int) -> None:
    key = key.strip().upper()
    if key not in _ENV_LIMITS:
        raise ValueError(f"알 수 없는 한도 키: {key}")
    conn.execute(
        """
        INSERT INTO quota_limits(key, value)
        VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (key, int(value)),
    )
    conn.commit()


@_with_conn
def reset_limits(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM quota_limits")
    conn.commit()


@_with_conn
def get_usage_summary_today(conn: sqlite3.Connection) -> Dict[str, Any]:
    day = _today()
    total = conn.execute(
        "SELECT calls, input_chars, output_tokens FROM usage_daily_total WHERE day=?",
        (day,),
    ).fetchone() or (0, 0, 0)
    per_chats = conn.execute(
        "SELECT chat_id, calls, input_chars, output_tokens FROM usage_daily WHERE day=? ORDER BY calls DESC",
        (day,),
    ).fetchall()
    return {"total": total, "per_chats": per_chats}


@_with_conn
def reset_usage(conn: sqlite3.Connection, scope: str = "today") -> None:
    if scope not in ("today", "all"):
        raise ValueError("scope must be 'today' or 'all'")
    if scope == "all":
        conn.execute("DELETE FROM usage_daily")
        conn.execute("DELETE FROM usage_daily_total")
    else:
        day = _today()
        conn.execute("DELETE FROM usage_daily WHERE day=?", (day,))
        conn.execute("DELETE FROM usage_daily_total WHERE day=?", (day,))
    conn.commit()


@_with_conn
def _add_usage(
    conn: sqlite3.Connection,
    chat_id: int,
    input_chars: int,
    output_tokens: int,
) -> None:
    day = _today()
    conn.execute(
        """
        INSERT INTO usage_daily(day, chat_id, calls, input_chars, output_tokens)
        VALUES(?,?,?,?,?)
        ON CONFLICT(day, chat_id) DO UPDATE SET
          calls = usage_daily.calls + excluded.calls,
          input_chars = usage_daily.input_chars + excluded.input_chars,
          output_tokens = usage_daily.output_tokens + excluded.output_tokens
        """,
        (day, chat_id, 1, int(input_chars), int(output_tokens)),
    )

    conn.execute(
        """
        INSERT INTO usage_daily_total(day, calls, input_chars, output_tokens)
        VALUES(?,?,?,?)
        ON CONFLICT(day) DO UPDATE SET
          calls = usage_daily_total.calls + excluded.calls,
          input_chars = usage_daily_total.input_chars + excluded.input_chars,
          output_tokens = usage_daily_total.output_tokens + excluded.output_tokens
        """,
        (day, 1, int(input_chars), int(output_tokens)),
    )
    conn.commit()


def add_usage(chat_id: int, input_chars: int, output_tokens: int) -> None:
    _add_usage(chat_id=chat_id, input_chars=input_chars, output_tokens=output_tokens)


@_with_conn
def _fetch_usage_snapshot(
    conn: sqlite3.Connection, chat_id: int
) -> Tuple[Tuple[int, int, int], Tuple[int, int, int]]:
    day = _today()
    total = conn.execute(
        "SELECT calls, input_chars, output_tokens FROM usage_daily_total WHERE day=?",
        (day,),
    ).fetchone() or (0, 0, 0)
    per_chat = conn.execute(
        "SELECT calls, input_chars, output_tokens FROM usage_daily WHERE day=? AND chat_id=?",
        (day, chat_id),
    ).fetchone() or (0, 0, 0)
    return total, per_chat


def _estimate_output_tokens_from_config(config: Any) -> int:
    """Best-effort estimate of maximum output tokens."""
    for attr in ("max_output_tokens", "max_tokens"):
        value = getattr(config, attr, None)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    # Some SDK objects expose a dict-like interface
    try:
        mapping = config if isinstance(config, dict) else config.to_dict()  # type: ignore[attr-defined]
    except Exception:
        mapping = None
    if isinstance(mapping, dict):
        for key in ("max_output_tokens", "max_tokens"):
            value = mapping.get(key)
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    continue
    return 0


def _check_quota_or_msg(chat_id: int, input_chars: int, config: Any) -> str | None:
    limits = get_limits()
    total, per_chat = _fetch_usage_snapshot(chat_id)

    t_calls, t_in, t_out = total
    c_calls, c_in, c_out = per_chat

    est_output = _estimate_output_tokens_from_config(config)

    will_calls = t_calls + 1
    will_in = t_in + int(input_chars)
    will_out = t_out + est_output

    if will_calls > limits["MAX_CALLS_PER_DAY"]:
        return f"오늘 호출 한도({limits['MAX_CALLS_PER_DAY']}회)를 초과했어요. 내일 다시 시도해 주세요!"
    if will_in > limits["MAX_INPUT_CHARS_PER_DAY"]:
        return "오늘 입력 용량 한도를 초과했어요. 메시지를 더 짧게 하거나 내일 다시 시도해 주세요!"
    if will_out > limits["MAX_OUTPUT_TOKENS_PER_DAY"]:
        return "오늘 출력 용량 한도를 초과했어요. 요약 모드로 전환하거나 내일 다시 시도해 주세요!"

    per_chat_limit = limits["MAX_CALLS_PER_CHAT_PER_DAY"]
    if per_chat_limit and (c_calls + 1) > per_chat_limit:
        return f"이 대화방의 오늘 호출 한도({per_chat_limit}회)를 넘었어요!"

    return None


__all__ = [
    "USAGE_DB_PATH",
    "get_limits",
    "set_limit",
    "reset_limits",
    "get_usage_summary_today",
    "reset_usage",
    "add_usage",
    "_check_quota_or_msg",
    "_estimate_output_tokens_from_config",
]
