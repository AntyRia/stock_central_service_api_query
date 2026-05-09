from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, Iterator, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from .config import Settings

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool = ThreadedConnectionPool(
            minconn=settings.db_pool_minconn,
            maxconn=settings.db_pool_maxconn,
            host=settings.db_host,
            port=settings.db_port,
            dbname=settings.db_name,
            user=settings.db_user,
            password=settings.db_password,
            connect_timeout=settings.db_connect_timeout,
        )

    @contextmanager
    def connection(self, *, readonly: bool = True) -> Iterator[psycopg2.extensions.connection]:
        conn = self._pool.getconn()
        try:
            conn.autocommit = False
            conn.set_session(readonly=readonly, autocommit=False)
            with conn.cursor() as cur:
                cur.execute("SET statement_timeout = %s", (self._settings.db_statement_timeout_ms,))
            yield conn
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            self._pool.putconn(conn)

    def fetch_all(self, sql: str, params: Optional[Iterable[Any]] = None) -> List[Dict[str, Any]]:
        with self.connection(readonly=True) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, tuple(params or ()))
                rows = cur.fetchall() or []
        return [self._normalize_row(dict(row)) for row in rows]

    def fetch_one(self, sql: str, params: Optional[Iterable[Any]] = None) -> Optional[Dict[str, Any]]:
        with self.connection(readonly=True) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, tuple(params or ()))
                row = cur.fetchone()
        if not row:
            return None
        return self._normalize_row(dict(row))

    def execute(self, sql: str, params: Optional[Iterable[Any]] = None, *, readonly: bool = False) -> None:
        with self.connection(readonly=readonly) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params or ()))

    def close(self) -> None:
        try:
            self._pool.closeall()
        except Exception:
            logger.exception("close db pool failed")

    def _normalize_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for key, value in row.items():
            if isinstance(value, Decimal):
                out[key] = float(value)
            elif isinstance(value, (date, datetime)):
                out[key] = value.isoformat()
            else:
                out[key] = value
        return out
