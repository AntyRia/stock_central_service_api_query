from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import yaml


def _load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"invalid config yaml: {path}")
    return data


@dataclass(frozen=True)
class Settings:
    timezone: str
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    db_pool_minconn: int
    db_pool_maxconn: int
    db_connect_timeout: int
    db_statement_timeout_ms: int
    redis_host: str
    redis_port: int
    redis_db: int
    redis_password: str
    redis_decode_responses: bool
    redis_socket_timeout: int
    redis_socket_connect_timeout: int
    redis_retry_on_timeout: bool
    redis_health_check_interval: int
    redis_max_connections: int
    cache_ttl_seconds: int
    cache_refresh_interval_seconds: int
    query_workers: int
    query_queue_max_size: int
    query_wait_timeout_seconds: int
    query_job_timeout_seconds: int
    default_token_scope: str
    queue_reject_status_code: int


def load_settings() -> Settings:
    root = Path(__file__).resolve().parent.parent
    config_path = Path(os.getenv("DATA_QUERY_SERVICE_CONFIG", root / "config" / "system_config.yaml"))
    cfg = _load_yaml(config_path)
    db_cfg = dict(cfg.get("database_server") or {})
    pool_cfg = dict(db_cfg.get("pool") or {})
    redis_cfg = dict(cfg.get("redis_server") or {})
    data_api_cfg = dict(cfg.get("data_api") or {})
    return Settings(
        timezone=str((cfg.get("general") or {}).get("timezone") or "Asia/Shanghai"),
        db_host=os.getenv("FIN_POSTGRES_HOST", str(db_cfg.get("host") or "finsight_postgresql_timescale")),
        db_port=int(os.getenv("FIN_POSTGRES_PORT", db_cfg.get("port") or 5432)),
        db_name=os.getenv("FIN_POSTGRES_DATABASE", str(db_cfg.get("database") or "stock_data")),
        db_user=os.getenv("FIN_POSTGRES_USER", str(db_cfg.get("user") or "user_admin")),
        db_password=os.getenv("FIN_POSTGRES_PASSWORD", str(db_cfg.get("password") or "")),
        db_pool_minconn=max(1, int(os.getenv("DATA_API_DB_POOL_MIN", pool_cfg.get("min_connections") or 1))),
        db_pool_maxconn=max(1, int(os.getenv("DATA_API_DB_POOL_MAX", pool_cfg.get("max_connections") or 4))),
        db_connect_timeout=max(1, int(os.getenv("DATA_API_DB_CONNECT_TIMEOUT", pool_cfg.get("connection_timeout") or 5))),
        db_statement_timeout_ms=max(1000, int(os.getenv("DATA_API_DB_STATEMENT_TIMEOUT_MS", pool_cfg.get("statement_timeout_ms") or 8000))),
        redis_host=os.getenv("REDIS_HOST", str(redis_cfg.get("host") or "redis")),
        redis_port=int(os.getenv("REDIS_PORT", redis_cfg.get("port") or 6379)),
        redis_db=int(os.getenv("REDIS_DB", redis_cfg.get("db") or 0)),
        redis_password=str(os.getenv("REDIS_PASSWORD", redis_cfg.get("password") or "")),
        redis_decode_responses=str(redis_cfg.get("decode_responses", True)).lower() not in {"0", "false", "no"},
        redis_socket_timeout=max(1, int(redis_cfg.get("socket_timeout") or 5)),
        redis_socket_connect_timeout=max(1, int(redis_cfg.get("socket_connect_timeout") or 5)),
        redis_retry_on_timeout=str(redis_cfg.get("retry_on_timeout", True)).lower() not in {"0", "false", "no"},
        redis_health_check_interval=max(1, int(redis_cfg.get("health_check_interval") or 30)),
        redis_max_connections=max(16, int(redis_cfg.get("max_connections") or 128)),
        cache_ttl_seconds=max(5, int(os.getenv("DATA_API_CACHE_TTL_SECONDS", data_api_cfg.get("cache_ttl_seconds") or 30))),
        cache_refresh_interval_seconds=max(5, int(os.getenv("DATA_API_CACHE_REFRESH_INTERVAL_SECONDS", data_api_cfg.get("cache_refresh_interval_seconds") or 20))),
        query_workers=max(1, int(os.getenv("DATA_API_QUERY_WORKERS", data_api_cfg.get("query_workers") or 2))),
        query_queue_max_size=max(1, int(os.getenv("DATA_API_QUERY_QUEUE_MAX_SIZE", data_api_cfg.get("query_queue_max_size") or 128))),
        query_wait_timeout_seconds=max(1, int(os.getenv("DATA_API_QUERY_WAIT_TIMEOUT_SECONDS", data_api_cfg.get("query_wait_timeout_seconds") or 8))),
        query_job_timeout_seconds=max(1, int(os.getenv("DATA_API_QUERY_JOB_TIMEOUT_SECONDS", data_api_cfg.get("query_job_timeout_seconds") or 10))),
        default_token_scope=str(os.getenv("DATA_API_TOKEN_SCOPE", data_api_cfg.get("default_token_scope") or "data_api")).strip() or "data_api",
        queue_reject_status_code=max(400, int(os.getenv("DATA_API_QUEUE_REJECT_STATUS", data_api_cfg.get("queue_reject_status_code") or 429))),
    )
