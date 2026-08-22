"""SQLite access layer for the Phase 8 API.

The database is opened read-only: the API never writes, so the pipeline scripts
stay the single source of truth and a rebuild can never be corrupted by a
running server.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parents[1]
# Mirrors the override in scripts/build_phase8_database.py so the API can be
# pointed at a test or deployment artifact directory.
DATA_DIR = Path(os.environ.get("TOURISTINBD_DATA_DIR") or (REPO_ROOT / "data"))
DB_PATH = DATA_DIR / "touristinbd.db"

# Must match SCHEMA_VERSION in scripts/build_phase8_database.py.
EXPECTED_SCHEMA_VERSION = 1

BUILD_HINT = (
    "Database not found or out of date. Build it with:\n"
    "  .venv/bin/python scripts/build_phase8_database.py"
)


class DatabaseUnavailable(RuntimeError):
    """Raised when the SQLite file is missing or built by an older schema."""


def connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise DatabaseUnavailable(f"{DB_PATH} does not exist. {BUILD_HINT}")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def get_conn() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: one read-only connection per request."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def rows(conn: sqlite3.Connection, sql: str, params: tuple | list = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params)]


def one(conn: sqlite3.Connection, sql: str, params: tuple | list = ()) -> dict | None:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def scalar(conn: sqlite3.Connection, sql: str, params: tuple | list = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def meta_value(conn: sqlite3.Connection, key: str) -> str | None:
    return scalar(conn, "SELECT value FROM metadata WHERE key = ?", (key,))


def meta_json(conn: sqlite3.Connection, key: str) -> Any:
    raw = meta_value(conn, key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def check_schema() -> dict:
    """Verify the DB exists and its schema version matches this code."""
    conn = connect()
    try:
        version = meta_value(conn, "schema_version")
        if version is None:
            raise DatabaseUnavailable(f"metadata.schema_version missing. {BUILD_HINT}")
        if int(version) != EXPECTED_SCHEMA_VERSION:
            raise DatabaseUnavailable(
                f"database schema version {version} != expected "
                f"{EXPECTED_SCHEMA_VERSION}. {BUILD_HINT}"
            )
        return {
            "schema_version": int(version),
            "built_at_utc": meta_value(conn, "built_at_utc"),
            "row_counts": meta_json(conn, "row_counts") or {},
        }
    finally:
        conn.close()


def like_term(text: str) -> str:
    """Build a LIKE pattern with %/_ escaped (paired with ESCAPE '\\')."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def paginate(
    conn: sqlite3.Connection,
    select_sql: str,
    count_sql: str,
    params: list,
    limit: int,
    offset: int,
    order_sql: str = "",
) -> dict:
    """Run a filtered query plus its matching COUNT and wrap the standard envelope."""
    total = scalar(conn, count_sql, params) or 0
    sql = f"{select_sql} {order_sql} LIMIT ? OFFSET ?"
    items = rows(conn, sql, params + [limit, offset])
    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "returned": len(items),
        "items": items,
    }
