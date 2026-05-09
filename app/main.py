from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from .auth import AuthContext, AuthService
from .config import Settings, load_settings
from .db import Database
from .logging_utils import setup_logging
from .query_queue import QueryQueueManager, QueueSaturatedError
from .redis_client import build_redis
from .schema import ensure_schema
from .snapshot_service import SnapshotService

setup_logging()
logger = logging.getLogger(__name__)

settings: Settings = load_settings()
db = Database(settings)
redis_client = build_redis(settings)
ensure_schema(db)
auth_service = AuthService(db, redis_client, settings)
snapshot_service = SnapshotService(db, redis_client, settings)
queue_manager = QueryQueueManager(snapshot_service, settings)
seed_admin = auth_service.ensure_seed_data_api_admin()

app = FastAPI(title="FinSight Data Query Service")
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

USAGE_ENDPOINT_DEFS = [
    {
        "key": "stock_sector_fund_flow_daily_latest",
        "sdk_method": "get_stock_sector_fund_flow_daily_latest",
        "label": "板块资金流向最新交易日",
        "path": "/api/data/latest/stock_sector_fund_flow_daily",
        "table": "stock_sector_fund_flow_daily",
        "description": "返回最新交易日全部板块资金流向数据，默认按主力净流入额从高到低排序。",
        "filters": ["board_type: 板块类型，支持 行业 / 概念 / 板块", "keyword: 按板块代码或名称模糊过滤"],
    },
    {
        "key": "stock_individual_fund_flow_daily_latest",
        "sdk_method": "get_stock_individual_fund_flow_daily_latest",
        "label": "个股资金流向最新交易日",
        "path": "/api/data/latest/stock_individual_fund_flow_daily",
        "table": "stock_individual_fund_flow_daily",
        "description": "返回最新交易日全部个股资金流向数据，默认按主力净流入额从高到低排序。",
        "filters": ["codes: 逗号分隔股票代码精确过滤", "keyword: 按股票代码或名称模糊过滤"],
    },
    {
        "key": "stock_daily_kline_q_latest",
        "sdk_method": "get_stock_daily_kline_q_latest",
        "label": "全市场前复权日线最新交易日",
        "path": "/api/data/latest/stock_daily_kline_q",
        "table": "stock_daily_kline_q",
        "description": "返回最新交易日全市场前复权日线 K 线数据，默认按成交额从高到低排序。",
        "filters": ["codes: 逗号分隔股票代码精确过滤", "keyword: 按股票代码或名称模糊过滤"],
    },
]


@app.on_event("startup")
async def on_startup() -> None:
    await queue_manager.start()
    logger.info("data_api admin token ready token_id=%s", seed_admin["token_id"])


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await queue_manager.stop()
    db.close()
    try:
        redis_client.close()
    except Exception:
        logger.exception("close redis failed")


@app.exception_handler(QueueSaturatedError)
async def handle_queue_saturated(_: Request, exc: QueueSaturatedError) -> JSONResponse:
    return JSONResponse(status_code=settings.queue_reject_status_code, content={"ok": False, "error": str(exc)})


def _parse_codes(codes: str) -> List[str]:
    return [item.strip() for item in str(codes or "").split(",") if item.strip()]


async def _fetch_table_payload(
    table_name: str,
    *,
    ctx: AuthContext,
    codes: Optional[List[str]] = None,
    keyword: str = "",
    board_type: str = "",
    limit: Optional[int] = None,
    offset: int = 0,
) -> Dict[str, Any]:
    auth_service.ensure_request_not_conflicted(ctx)
    snapshot = snapshot_service.get_cached_snapshot(table_name)
    if snapshot is None:
        snapshot = await queue_manager.get_snapshot(
            table_name=table_name,
            token_id=ctx.token_id,
            max_queue=ctx.quota_max_queue,
        )
    auth_service.ensure_request_not_conflicted(ctx)
    payload = snapshot_service.filter_rows(
        snapshot,
        codes=codes or [],
        keyword=keyword,
        board_type=board_type,
        limit=limit,
        offset=offset,
    )
    auth_service.ensure_request_not_conflicted(ctx)
    return {"ok": True, **payload}


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {"ok": True, "service": "data_query_service"}


@app.get("/")
async def admin_index() -> RedirectResponse:
    return RedirectResponse(url="/web/auth/data-api-console", status_code=307)


@app.get("/api/admin/bootstrap-token")
async def admin_bootstrap_token() -> Dict[str, Any]:
    return {"ok": True, "token": seed_admin["token"]}


@app.get("/api/data/latest/stock_sector_fund_flow_daily")
async def stock_sector_fund_flow_daily_latest(
    board_type: str = Query("", description="板块类型，可选：行业/概念/板块"),
    keyword: str = Query(""),
    limit: Optional[int] = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    ctx: AuthContext = Depends(auth_service.get_data_token_dependency(table_name="stock_sector_fund_flow_daily")),
) -> Dict[str, Any]:
    return await _fetch_table_payload(
        "stock_sector_fund_flow_daily",
        ctx=ctx,
        keyword=keyword,
        board_type=board_type,
        limit=limit,
        offset=offset,
    )


@app.get("/api/data/latest/stock_individual_fund_flow_daily")
async def stock_individual_fund_flow_daily_latest(
    codes: str = Query(""),
    keyword: str = Query(""),
    limit: Optional[int] = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    ctx: AuthContext = Depends(auth_service.get_data_token_dependency(table_name="stock_individual_fund_flow_daily")),
) -> Dict[str, Any]:
    return await _fetch_table_payload(
        "stock_individual_fund_flow_daily",
        ctx=ctx,
        codes=_parse_codes(codes),
        keyword=keyword,
        limit=limit,
        offset=offset,
    )


@app.get("/api/data/latest/stock_daily_kline_q")
async def stock_daily_kline_q_latest(
    codes: str = Query(""),
    keyword: str = Query(""),
    limit: Optional[int] = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    ctx: AuthContext = Depends(auth_service.get_data_token_dependency(table_name="stock_daily_kline_q")),
) -> Dict[str, Any]:
    return await _fetch_table_payload(
        "stock_daily_kline_q",
        ctx=ctx,
        codes=_parse_codes(codes),
        keyword=keyword,
        limit=limit,
        offset=offset,
    )


@app.get("/api/admin/queue/status")
async def admin_queue_status(
    _: AuthContext = Depends(auth_service.get_data_admin_dependency()),
) -> Dict[str, Any]:
    return {"ok": True, "queue": queue_manager.runtime_status()}


def _token_usage_payload(token_row: Dict[str, Any]) -> Dict[str, Any]:
    return auth_service.build_usage_snapshot(
        token_id=str(token_row["token_id"]),
        rate_limit_per_minute=int(token_row.get("rate_limit_per_minute")) if token_row.get("rate_limit_per_minute") is not None else -1,
        rate_limit_per_hour=int(token_row.get("rate_limit_per_hour")) if token_row.get("rate_limit_per_hour") is not None else -1,
        rate_limit_per_day=int(token_row.get("rate_limit_per_day")) if token_row.get("rate_limit_per_day") is not None else -1,
        endpoint_defs=USAGE_ENDPOINT_DEFS,
    )


def _token_view_payload(token_row: Dict[str, Any]) -> Dict[str, Any]:
    usage = _token_usage_payload(token_row)
    return {
        **token_row,
        "quota_max_concurrent": 1,
        "token_masked": f"{str(token_row['token'])[:6]}...{str(token_row['token'])[-6:]}",
        "usage": usage,
    }


def _limit_value(value: int) -> Optional[int]:
    return None if int(value) < 0 else int(value)


def _window_usage_payload(*, limit: int, used: int, resets_at: str) -> Dict[str, Any]:
    normalized_limit = _limit_value(limit)
    return {
        "limit": normalized_limit,
        "used": int(used),
        "remaining": None if normalized_limit is None else max(0, normalized_limit - int(used)),
        "resets_at": resets_at,
    }


def _public_token_usage_payload(ctx: AuthContext) -> Dict[str, Any]:
    usage = auth_service.build_usage_snapshot(
        token_id=ctx.token_id,
        rate_limit_per_minute=ctx.rate_limit_per_minute,
        rate_limit_per_hour=ctx.rate_limit_per_hour,
        rate_limit_per_day=ctx.rate_limit_per_day,
        endpoint_defs=USAGE_ENDPOINT_DEFS,
    )
    summary = usage["summary"]
    summary_reset = summary.get("resets_at") or {}
    usage_by_path = {str(item["path"]): item for item in usage["by_endpoint"]}

    endpoints: List[Dict[str, Any]] = []
    for item in USAGE_ENDPOINT_DEFS:
        usage_item = usage_by_path[str(item["path"])]
        used = usage_item["used"]
        resets_at = usage_item.get("resets_at") or summary_reset
        endpoints.append(
            {
                "sdk_method": str(item["sdk_method"]),
                "name": str(item["label"]),
                "minute_limit": _limit_value(ctx.rate_limit_per_minute),
                "minute_used": int(used["minute"]),
                "minute_remaining": _window_usage_payload(
                    limit=ctx.rate_limit_per_minute,
                    used=int(used["minute"]),
                    resets_at=str(resets_at.get("minute") or ""),
                )["remaining"],
                "hour_limit": _limit_value(ctx.rate_limit_per_hour),
                "hour_used": int(used["hour"]),
                "hour_remaining": _window_usage_payload(
                    limit=ctx.rate_limit_per_hour,
                    used=int(used["hour"]),
                    resets_at=str(resets_at.get("hour") or ""),
                )["remaining"],
                "day_limit": _limit_value(ctx.rate_limit_per_day),
                "day_used": int(used["day"]),
                "day_remaining": _window_usage_payload(
                    limit=ctx.rate_limit_per_day,
                    used=int(used["day"]),
                    resets_at=str(resets_at.get("day") or ""),
                )["remaining"],
                "minute_resets_at": str(resets_at.get("minute") or ""),
                "hour_resets_at": str(resets_at.get("hour") or ""),
                "day_resets_at": str(resets_at.get("day") or ""),
            }
        )

    return {
        "ok": True,
        "items": endpoints,
    }


@app.get("/api/token/usage")
async def token_usage(
    ctx: AuthContext = Depends(auth_service.get_data_token_dependency(count_usage=False)),
) -> Dict[str, Any]:
    auth_service.ensure_request_not_conflicted(ctx)
    auth_service.ensure_request_not_conflicted(ctx)
    return _public_token_usage_payload(ctx)


@app.get("/api/admin/tokens")
async def admin_tokens(
    _: AuthContext = Depends(auth_service.get_data_admin_dependency()),
) -> Dict[str, Any]:
    rows = db.fetch_all(
        """
        SELECT
          t.id::text AS token_id,
          t.user_id::text AS user_id,
          COALESCE(u.username, '') AS username,
          COALESCE(u.email, '') AS email,
          t.token,
          COALESCE(t.name, '') AS name,
          COALESCE(NULLIF(t.token_scope, ''), 'dashboard') AS token_scope,
          t.enabled,
          COALESCE(t.is_valid, TRUE) AS is_valid,
          t.expires_at,
          t.banned_until,
          COALESCE(t.rate_limit_per_minute, -1) AS rate_limit_per_minute,
          COALESCE(t.rate_limit_per_hour, -1) AS rate_limit_per_hour,
          COALESCE(t.rate_limit_per_day, -1) AS rate_limit_per_day,
          COALESCE(t.quota_max_concurrent, -1) AS quota_max_concurrent,
          COALESCE(t.quota_max_queue, -1) AS quota_max_queue,
          COALESCE(t.allowed_tables, '[]'::jsonb) AS allowed_tables,
          COALESCE(t.device_fingerprint_hash, '') AS device_fingerprint_hash,
          COALESCE(NULLIF(t.fingerprint_binding_mode, ''), 'optional') AS fingerprint_binding_mode,
          COALESCE(t.device_rebind_remaining, 1) AS device_rebind_remaining,
          COALESCE(t.issued_via, '') AS issued_via,
          t.created_at
        FROM auth_token t
        LEFT JOIN auth_user u ON u.id = t.user_id
        WHERE COALESCE(NULLIF(t.token_scope, ''), 'dashboard') = %s
        ORDER BY t.created_at DESC
        """,
        (settings.default_token_scope,),
    )
    tokens: List[Dict[str, Any]] = []
    for row in rows:
        token_id = str(row["token_id"])
        tokens.append(_token_view_payload({**row, "token_id": token_id}))
        tokens[-1].pop("token", None)
    return {"ok": True, "tokens": tokens, "seed_admin_token_id": seed_admin["token_id"]}


@app.get("/api/admin/tokens/usage")
async def admin_tokens_usage(
    _: AuthContext = Depends(auth_service.get_data_admin_dependency()),
) -> Dict[str, Any]:
    payload = await admin_tokens(_)
    queue_status = queue_manager.runtime_status()
    return {"ok": True, "tokens": payload["tokens"], "queue": queue_status, "seed_admin_token_id": seed_admin["token_id"]}
