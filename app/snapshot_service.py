from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .config import Settings
from .db import Database
from .tables import TABLES, TableDefinition

logger = logging.getLogger(__name__)


@dataclass
class SnapshotResult:
    table: str
    trade_date: str
    rows: List[Dict[str, Any]]
    row_count: int
    refreshed_at: str
    source: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "table": self.table,
            "trade_date": self.trade_date,
            "rows": self.rows,
            "row_count": self.row_count,
            "refreshed_at": self.refreshed_at,
            "source": self.source,
        }


class SnapshotService:
    def __init__(self, db: Database, redis_client, settings: Settings) -> None:
        self._db = db
        self._redis = redis_client
        self._settings = settings
        self._memory: Dict[str, tuple[float, SnapshotResult]] = {}

    def _cache_key(self, table_name: str) -> str:
        return f"data_api:snapshot:v1:{table_name}"

    def list_supported_tables(self) -> List[str]:
        return list(TABLES.keys())

    def get_cached_snapshot(self, table_name: str, *, max_age_seconds: Optional[int] = None) -> Optional[SnapshotResult]:
        if table_name not in TABLES:
            return None
        ttl = max_age_seconds if max_age_seconds is not None else self._settings.cache_ttl_seconds
        item = self._memory.get(table_name)
        if item and time.monotonic() - item[0] <= ttl:
            cached = item[1]
            cached.source = "memory"
            return cached
        payload = self._redis.get(self._cache_key(table_name))
        if payload:
            try:
                data = json.loads(payload)
                snapshot = SnapshotResult(
                    table=str(data["table"]),
                    trade_date=str(data["trade_date"]),
                    rows=list(data["rows"]),
                    row_count=int(data["row_count"]),
                    refreshed_at=str(data["refreshed_at"]),
                    source="redis",
                )
                self._memory[table_name] = (time.monotonic(), snapshot)
                return snapshot
            except Exception:
                logger.exception("decode cached snapshot failed table=%s", table_name)
        return None

    def refresh_snapshot(self, table_name: str) -> SnapshotResult:
        if table_name not in TABLES:
            raise ValueError(f"unsupported table: {table_name}")
        table = TABLES[table_name]
        rows = self._db.fetch_all(
            f"""
            WITH latest_day AS (
              SELECT MAX(date) AS trade_date
              FROM {table.name}
            )
            SELECT t.*
            FROM {table.name} t
            JOIN latest_day d ON t.date = d.trade_date
            ORDER BY {table.order_by}
            """
        )
        if not rows:
            raise ValueError(f"table {table_name} has no rows")
        trade_date = str(rows[0]["date"])
        refreshed_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        snapshot = SnapshotResult(
            table=table_name,
            trade_date=trade_date,
            rows=rows,
            row_count=len(rows),
            refreshed_at=refreshed_at,
            source="db",
        )
        self._memory[table_name] = (time.monotonic(), snapshot)
        self._redis.setex(self._cache_key(table_name), max(5, self._settings.cache_ttl_seconds * 3), json.dumps(snapshot.to_dict(), ensure_ascii=False))
        return snapshot

    def filter_rows(
        self,
        snapshot: SnapshotResult,
        *,
        codes: Optional[List[str]] = None,
        keyword: str = "",
        board_type: str = "",
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> Dict[str, Any]:
        definition: TableDefinition = TABLES[snapshot.table]
        rows = snapshot.rows
        if codes:
            code_set = {item.strip() for item in codes if item.strip()}
            rows = [row for row in rows if str(row.get(definition.code_column) or "").strip() in code_set]
        keyword = str(keyword or "").strip().lower()
        if keyword:
            rows = [
                row
                for row in rows
                if keyword in str(row.get(definition.code_column) or "").lower()
                or keyword in str(row.get(definition.name_column) or "").lower()
            ]
        if board_type and snapshot.table == "stock_sector_fund_flow_daily":
            board_type_norm = str(board_type).strip()
            rows = [row for row in rows if str(row.get("type") or "").strip() == board_type_norm]
        total = len(rows)
        safe_offset = max(0, offset)
        safe_limit = None if limit is None else max(1, int(limit))
        sliced = rows[safe_offset:] if safe_limit is None else rows[safe_offset : safe_offset + safe_limit]
        public_rows = [definition.project_row(row) for row in sliced]
        return {
            "trade_date": snapshot.trade_date,
            "total": total,
            "items": public_rows,
        }
