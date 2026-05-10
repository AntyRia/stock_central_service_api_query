from __future__ import annotations

import hashlib
import json
import logging
import math
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterator, List, Optional

from fastapi import Depends, HTTPException, Request

from .config import Settings
from .db import Database
from .schema import normalize_allowed_tables
from .time_utils import get_now

logger = logging.getLogger(__name__)

TOKEN_CACHE_TTL_SECONDS = 5.0
CONCURRENT_KEY_TTL_SECONDS = 90
DEFAULT_FINGERPRINT_BAN_SECONDS = 24 * 3600
FORCED_MAX_CONCURRENT_PER_TOKEN = 1


@dataclass
class AuthContext:
    token_id: str
    user_id: str
    token: str
    enabled: bool
    is_valid: bool
    restore_valid_at: Optional[datetime]
    expires_at: Optional[datetime]
    expired: bool
    banned_until: Optional[datetime]
    ban_reason: str
    username: str
    email: str
    status: int
    role_names: List[str]
    token_scope: str
    rate_limit_per_minute: int
    rate_limit_per_hour: int
    rate_limit_per_day: int
    quota_max_concurrent: int
    quota_max_queue: int
    allowed_tables: List[str]
    device_fingerprint_hash: str
    fingerprint_binding_mode: str
    device_rebind_remaining: int
    token_meta: Dict[str, Any]
    active_request_id: str = ""


def validate_token_format(token: str) -> bool:
    if not token or not isinstance(token, str):
        return False
    if len(token) != 64:
        return False
    try:
        int(token, 16)
    except Exception:
        return False
    return True


def extract_token_from_request(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "") or ""
    if auth_header.startswith("Bearer "):
        return auth_header[7:].strip()
    return str(request.query_params.get("token") or "").strip()


def client_ip(request: Request) -> str:
    forwarded = str(request.headers.get("X-Forwarded-For") or "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = str(request.headers.get("X-Real-IP") or "").strip()
    if real_ip:
        return real_ip
    if request.client and request.client.host:
        return str(request.client.host).strip()
    return ""


def mask_token(token: str) -> str:
    token = str(token or "").strip()
    if len(token) < 12:
        return token
    return f"{token[:6]}...{token[-6:]}"


def bool_from_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


def datetime_from_value(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            if text.endswith("Z"):
                try:
                    return datetime.fromisoformat(f"{text[:-1]}+00:00")
                except ValueError:
                    return None
    return None


class AuthService:
    def __init__(self, db: Database, redis_client, settings: Settings) -> None:
        self._db = db
        self._redis = redis_client
        self._settings = settings
        self._cache: Dict[str, tuple[float, Optional[AuthContext]]] = {}

    def _cache_get(self, token: str) -> Optional[AuthContext]:
        item = self._cache.get(token)
        if not item:
            return None
        if time.monotonic() > item[0]:
            self._cache.pop(token, None)
            return None
        return item[1]

    def invalidate_token_cache(self, token: str) -> None:
        self._cache.pop(token, None)

    @staticmethod
    def is_admin(ctx: AuthContext) -> bool:
        return any(str(role or "").strip().lower() == "admin" for role in ctx.role_names)

    def load_token_context(self, token: str) -> Optional[AuthContext]:
        cached = self._cache_get(token)
        if cached is not None or token in self._cache:
            return cached
        row = self._db.fetch_one(
            """
            SELECT
              t.id::text AS token_id,
              t.user_id::text AS user_id,
              t.token,
              t.enabled,
              COALESCE(t.is_valid, TRUE) AS is_valid,
              t.restore_valid_at,
              t.expires_at,
              (t.expires_at IS NOT NULL AND t.expires_at <= NOW()) AS expired,
              t.banned_until,
              COALESCE(t.ban_reason, '') AS ban_reason,
              COALESCE(u.username, '') AS username,
              COALESCE(u.email, '') AS email,
              COALESCE(u.status, 1) AS user_status,
              COALESCE(array_agg(r.name) FILTER (WHERE r.name IS NOT NULL), ARRAY[]::text[]) AS role_names,
              COALESCE(NULLIF(t.token_scope, ''), 'dashboard') AS token_scope,
              COALESCE(t.rate_limit_per_minute, -1) AS rate_limit_per_minute,
              COALESCE(t.rate_limit_per_hour, -1) AS rate_limit_per_hour,
              COALESCE(t.rate_limit_per_day, -1) AS rate_limit_per_day,
              COALESCE(t.quota_max_concurrent, -1) AS quota_max_concurrent,
              COALESCE(t.quota_max_queue, -1) AS quota_max_queue,
              COALESCE(t.allowed_tables, '[]'::jsonb) AS allowed_tables,
              COALESCE(t.device_fingerprint_hash, '') AS device_fingerprint_hash,
              COALESCE(NULLIF(t.fingerprint_binding_mode, ''), 'optional') AS fingerprint_binding_mode,
              COALESCE(t.device_rebind_remaining, 1) AS device_rebind_remaining,
              COALESCE(t.token_meta, '{}'::jsonb) AS token_meta
            FROM auth_token t
            LEFT JOIN auth_user u ON u.id = t.user_id
            LEFT JOIN auth_user_role ur ON ur.user_id = u.id
            LEFT JOIN auth_role r ON r.id = ur.role_id
            WHERE t.token = %s
            GROUP BY
              t.id, t.user_id, t.token, t.enabled, t.is_valid, t.restore_valid_at, t.expires_at,
              t.banned_until, t.ban_reason, u.username, u.email, u.status, t.token_scope,
              t.rate_limit_per_minute, t.rate_limit_per_hour, t.rate_limit_per_day, t.quota_max_concurrent,
              t.quota_max_queue, t.allowed_tables, t.device_fingerprint_hash, t.fingerprint_binding_mode,
              t.device_rebind_remaining, t.token_meta
            """,
            (token,),
        )
        ctx: Optional[AuthContext] = None
        if row:
            token_meta = row.get("token_meta")
            if not isinstance(token_meta, dict):
                token_meta = {}
            ctx = AuthContext(
                token_id=str(row["token_id"]),
                user_id=str(row["user_id"]),
                token=str(row["token"]),
                enabled=bool(row["enabled"]),
                is_valid=bool(row["is_valid"]),
                restore_valid_at=datetime_from_value(row.get("restore_valid_at")),
                expires_at=datetime_from_value(row.get("expires_at")),
                expired=bool(row.get("expired")),
                banned_until=datetime_from_value(row.get("banned_until")),
                ban_reason=str(row.get("ban_reason") or ""),
                username=str(row.get("username") or ""),
                email=str(row.get("email") or ""),
                status=int(row.get("user_status") or 1),
                role_names=[str(x or "").strip() for x in list(row.get("role_names") or []) if str(x or "").strip()],
                token_scope=str(row.get("token_scope") or "dashboard").strip() or "dashboard",
                rate_limit_per_minute=int(row.get("rate_limit_per_minute")) if row.get("rate_limit_per_minute") is not None else -1,
                rate_limit_per_hour=int(row.get("rate_limit_per_hour")) if row.get("rate_limit_per_hour") is not None else -1,
                rate_limit_per_day=int(row.get("rate_limit_per_day")) if row.get("rate_limit_per_day") is not None else -1,
                quota_max_concurrent=int(row.get("quota_max_concurrent")) if row.get("quota_max_concurrent") is not None else -1,
                quota_max_queue=int(row.get("quota_max_queue")) if row.get("quota_max_queue") is not None else -1,
                allowed_tables=normalize_allowed_tables(row.get("allowed_tables")),
                device_fingerprint_hash=str(row.get("device_fingerprint_hash") or "").strip(),
                fingerprint_binding_mode=str(row.get("fingerprint_binding_mode") or "optional").strip() or "optional",
                device_rebind_remaining=int(row.get("device_rebind_remaining")) if row.get("device_rebind_remaining") is not None else 1,
                token_meta=token_meta,
            )
        self._cache[token] = (time.monotonic() + TOKEN_CACHE_TTL_SECONDS, ctx)
        return ctx

    def record_security_event(
        self,
        *,
        token_id: str = "",
        user_id: str = "",
        event_type: str,
        path: str = "",
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not event_type:
            return
        self._db.execute(
            """
            INSERT INTO auth_security_event(id, token_id, user_id, event_type, path, detail)
            VALUES (%s, NULLIF(%s, '')::uuid, NULLIF(%s, '')::uuid, %s, %s, %s::jsonb)
            """,
            (
                str(uuid.uuid4()),
                str(token_id or "").strip(),
                str(user_id or "").strip(),
                str(event_type).strip(),
                str(path or "").strip(),
                json.dumps(detail or {}, ensure_ascii=False),
            ),
        )

    def record_audit_event(
        self,
        *,
        token_id: str = "",
        user_id: str = "",
        event_type: str,
        title: str = "",
        reason_code: str = "",
        detail: Optional[Dict[str, Any]] = None,
        operator_type: str = "system",
        operator_id: str = "",
    ) -> None:
        if not event_type:
            return
        self._db.execute(
            """
            INSERT INTO auth_token_audit_log(
              id, token_id, user_id, event_type, title, reason_code, detail, operator_type, operator_id
            )
            VALUES (%s, NULLIF(%s, '')::uuid, NULLIF(%s, '')::uuid, %s, %s, %s, %s::jsonb, %s, %s)
            """,
            (
                str(uuid.uuid4()),
                str(token_id or "").strip(),
                str(user_id or "").strip(),
                str(event_type).strip(),
                str(title or "").strip(),
                str(reason_code or "").strip(),
                json.dumps(detail or {}, ensure_ascii=False),
                str(operator_type or "system").strip() or "system",
                str(operator_id or "").strip(),
            ),
        )

    def bind_fingerprint(self, ctx: AuthContext, raw_fingerprint: str) -> None:
        digest = hashlib.sha256(raw_fingerprint.encode("utf-8")).hexdigest()
        if digest == ctx.device_fingerprint_hash:
            return
        self._db.execute(
            """
            UPDATE auth_token
            SET device_fingerprint_hash = %s,
                device_fingerprint_bound_at = NOW(),
                last_used_at = NOW()
            WHERE id = %s::uuid
            """,
            (digest, ctx.token_id),
        )
        ctx.device_fingerprint_hash = digest
        self.invalidate_token_cache(ctx.token)
        self.record_audit_event(
            token_id=ctx.token_id,
            user_id=ctx.user_id,
            event_type="device_fingerprint_bound",
            title="数据 API 设备指纹已绑定",
            reason_code="data_api_device_bound",
            detail={"fingerprint_hash": digest[:16]},
        )

    def rebind_fingerprint(self, ctx: AuthContext, raw_fingerprint: str, *, path: str, ip: str) -> None:
        digest = hashlib.sha256(raw_fingerprint.encode("utf-8")).hexdigest()
        if digest == ctx.device_fingerprint_hash:
            return
        remaining_before = max(0, int(ctx.device_rebind_remaining or 0))
        if remaining_before <= 0:
            raise HTTPException(status_code=403, detail="Token 已绑定其他设备，且换绑机会已用尽")
        self._db.execute(
            """
            UPDATE auth_token
            SET device_fingerprint_hash = %s,
                device_fingerprint_bound_at = NOW(),
                device_rebind_remaining = GREATEST(COALESCE(device_rebind_remaining, 0) - 1, 0),
                last_used_at = NOW()
            WHERE id = %s::uuid
            """,
            (digest, ctx.token_id),
        )
        ctx.device_fingerprint_hash = digest
        ctx.device_rebind_remaining = max(0, remaining_before - 1)
        self.invalidate_token_cache(ctx.token)
        self.record_security_event(
            token_id=ctx.token_id,
            user_id=ctx.user_id,
            event_type="device_fingerprint_rebound",
            path=path,
            detail={
                "remaining_before": remaining_before,
                "remaining_after": max(0, remaining_before - 1),
                "fingerprint_hash": digest[:16],
                "ip": ip,
            },
        )
        self.record_audit_event(
            token_id=ctx.token_id,
            user_id=ctx.user_id,
            event_type="device_fingerprint_rebound",
            title="数据 API 设备指纹已换绑",
            reason_code="data_api_device_rebind",
            detail={
                "remaining_before": remaining_before,
                "remaining_after": max(0, remaining_before - 1),
                "fingerprint_hash": digest[:16],
                "ip": ip,
            },
        )

    def ban_token(self, ctx: AuthContext, *, seconds: int, reason: str, detail: Optional[Dict[str, Any]] = None) -> None:
        seconds = max(60, int(seconds or DEFAULT_FINGERPRINT_BAN_SECONDS))
        self._db.execute(
            """
            UPDATE auth_token
            SET banned_until = NOW() + (%s * INTERVAL '1 second'),
                is_valid = FALSE,
                restore_valid_at = NOW() + (%s * INTERVAL '1 second'),
                ban_reason = %s,
                ban_detail = %s::jsonb,
                last_state_detail = %s::jsonb,
                last_status_changed_at = NOW(),
                ban_count = COALESCE(ban_count, 0) + 1,
                last_banned_at = NOW()
            WHERE id = %s::uuid
            """,
            (
                seconds,
                seconds,
                str(reason or "security_violation").strip(),
                json.dumps(detail or {}, ensure_ascii=False),
                json.dumps({"status": "banned", "reason": reason, **(detail or {})}, ensure_ascii=False),
                ctx.token_id,
            ),
        )
        self.invalidate_token_cache(ctx.token)
        self.record_security_event(
            token_id=ctx.token_id,
            user_id=ctx.user_id,
            event_type="token_banned",
            detail={"reason": reason, "seconds": seconds, **(detail or {})},
        )
        self.record_audit_event(
            token_id=ctx.token_id,
            user_id=ctx.user_id,
            event_type="token_banned",
            title="数据 API Token 已封禁",
            reason_code=str(reason or "security_violation").strip(),
            detail={"seconds": seconds, **(detail or {})},
        )

    def _current_time(self) -> datetime:
        return get_now(self._settings.timezone)

    def _ensure_token_state(self, ctx: AuthContext) -> None:
        now = self._current_time()
        if not ctx.enabled:
            raise HTTPException(status_code=403, detail="Token 已被禁用")
        if ctx.status != 1:
            raise HTTPException(status_code=403, detail="用户已被禁用")
        if ctx.banned_until and ctx.banned_until > now:
            raise HTTPException(status_code=403, detail=f"Token 已封禁至 {ctx.banned_until.isoformat()}")
        if not ctx.is_valid and ctx.restore_valid_at and ctx.restore_valid_at > now:
            raise HTTPException(status_code=403, detail=f"Token 当前无效，预计 {ctx.restore_valid_at.isoformat()} 恢复")
        if ctx.expired or (ctx.expires_at and ctx.expires_at <= now):
            raise HTTPException(status_code=403, detail="Token 已过期")

    def _check_scope(self, ctx: AuthContext, required_scope: str) -> None:
        if ctx.token_scope != required_scope:
            raise HTTPException(
                status_code=403,
                detail=f"当前 Token 作用域为 {ctx.token_scope}，不能访问 {required_scope} 服务",
            )

    def _check_admin(self, ctx: AuthContext) -> None:
        if not any(role.lower() == "admin" for role in ctx.role_names):
            raise HTTPException(status_code=403, detail="需要 dashboard admin token")

    def _check_allowed_tables(self, ctx: AuthContext, table_name: Optional[str]) -> None:
        if self.is_admin(ctx):
            return
        if not table_name:
            return
        if ctx.allowed_tables and table_name not in ctx.allowed_tables:
            raise HTTPException(status_code=403, detail=f"当前 Token 未授权访问表 {table_name}")

    @staticmethod
    def normalize_usage_path(path: str) -> str:
        normalized = str(path or "").strip() or "/"
        if "?" in normalized:
            normalized = normalized.split("?", 1)[0]
        return normalized

    @classmethod
    def usage_path_key(cls, path: str) -> str:
        normalized = cls.normalize_usage_path(path)
        return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:20]

    def usage_counter_keys(self, token_id: str, path: str) -> Dict[str, str]:
        normalized_path = self.normalize_usage_path(path)
        path_key = self.usage_path_key(normalized_path)
        now_epoch = time.time()
        minute_key = int(math.floor(now_epoch / 60.0))
        hour_key = int(math.floor(now_epoch / 3600.0))
        day_key = int(self._current_time().strftime("%Y%m%d"))
        return {
            "path": normalized_path,
            "path_key": path_key,
            "minute": f"data_api:rate:minute:{token_id}:{path_key}:{minute_key}",
            "hour": f"data_api:rate:hour:{token_id}:{path_key}:{hour_key}",
            "day": f"data_api:rate:day:{token_id}:{path_key}:{day_key}",
        }

    def current_usage_counts(self, token_id: str, path: str) -> Dict[str, int]:
        keys = self.usage_counter_keys(token_id, path)
        return {
            "minute": int(self._redis.get(keys["minute"]) or 0),
            "hour": int(self._redis.get(keys["hour"]) or 0),
            "day": int(self._redis.get(keys["day"]) or 0),
        }

    def usage_window_reset_times(self) -> Dict[str, str]:
        now = self._current_time()
        minute_reset = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        hour_reset = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        day_reset = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        return {
            "minute": minute_reset.isoformat(),
            "hour": hour_reset.isoformat(),
            "day": day_reset.isoformat(),
        }

    def build_usage_snapshot(
        self,
        *,
        token_id: str,
        rate_limit_per_minute: int,
        rate_limit_per_hour: int,
        rate_limit_per_day: int,
        endpoint_defs: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        summary = {"minute": 0, "hour": 0, "day": 0}
        reset_times = self.usage_window_reset_times()
        by_endpoint: List[Dict[str, Any]] = []
        for item in endpoint_defs:
            label = str(item.get("label") or item.get("path") or "-").strip()
            path = self.normalize_usage_path(str(item.get("path") or "").strip())
            counts = self.current_usage_counts(token_id, path)
            limits = {
                "minute": int(rate_limit_per_minute or -1),
                "hour": int(rate_limit_per_hour or -1),
                "day": int(rate_limit_per_day or -1),
            }
            summary["minute"] += counts["minute"]
            summary["hour"] += counts["hour"]
            summary["day"] += counts["day"]
            by_endpoint.append(
                {
                    "label": label,
                    "path": path,
                    "used": counts,
                    "limit": limits,
                    "remaining": {
                        "minute": None if limits["minute"] < 0 else max(0, limits["minute"] - counts["minute"]),
                        "hour": None if limits["hour"] < 0 else max(0, limits["hour"] - counts["hour"]),
                        "day": None if limits["day"] < 0 else max(0, limits["day"] - counts["day"]),
                    },
                    "resets_at": reset_times,
                }
            )
        return {
            "summary": {
                **summary,
                "concurrent": 1 if self.current_request_id(token_id) else 0,
                "resets_at": reset_times,
            },
            "by_endpoint": by_endpoint,
        }

    @staticmethod
    def _allow_rebind(request: Request) -> bool:
        return bool_from_value(request.query_params.get("allow_rebind")) or bool_from_value(request.headers.get("X-Allow-Device-Rebind"))

    def _enforce_fingerprint(self, request: Request, ctx: AuthContext) -> None:
        mode = ctx.fingerprint_binding_mode
        raw_fp = str(request.headers.get("X-Device-Fingerprint") or "").strip()
        if mode == "disabled":
            return
        if mode in {"required", "bind_on_first_use"} and not raw_fp:
            raise HTTPException(status_code=403, detail="缺少 X-Device-Fingerprint")
        if not raw_fp:
            return
        digest = hashlib.sha256(raw_fp.encode("utf-8")).hexdigest()
        if ctx.device_fingerprint_hash:
            if secrets.compare_digest(ctx.device_fingerprint_hash, digest):
                return
            detail = {
                "token_scope": ctx.token_scope,
                "expected_fingerprint_hash": ctx.device_fingerprint_hash[:16],
                "actual_fingerprint_hash": digest[:16],
                "ip": client_ip(request),
            }
            self.record_security_event(
                token_id=ctx.token_id,
                user_id=ctx.user_id,
                event_type="device_fingerprint_mismatch",
                path=str(request.url.path),
                detail=detail,
            )
            if not self._allow_rebind(request):
                raise HTTPException(
                    status_code=403,
                    detail="设备指纹与 Token 绑定不一致。如需迁移到新设备，请显式传 allow_rebind=true；每个 Token 仅允许一次换绑",
                )
            if int(ctx.device_rebind_remaining or 0) <= 0:
                raise HTTPException(status_code=403, detail="设备指纹与 Token 绑定不一致，且换绑机会已用尽")
            self.rebind_fingerprint(
                ctx,
                raw_fp,
                path=str(request.url.path),
                ip=client_ip(request),
            )
            return
        if mode in {"required", "bind_on_first_use"}:
            self.bind_fingerprint(ctx, raw_fp)

    def _enforce_rate_limits(self, ctx: AuthContext, path: str) -> None:
        minute_limit = int(ctx.rate_limit_per_minute or -1)
        hour_limit = int(ctx.rate_limit_per_hour or -1)
        day_limit = int(ctx.rate_limit_per_day or -1)
        if not self.is_admin(ctx) and (minute_limit <= 0 or hour_limit <= 0 or day_limit <= 0):
            raise HTTPException(status_code=403, detail="当前 data_api token 未配置完整配额，已拒绝访问")

        keys = self.usage_counter_keys(ctx.token_id, path)
        checks = [
            (keys["minute"], 90, minute_limit, "分钟"),
            (keys["hour"], 3700, hour_limit, "小时"),
            (keys["day"], 90000, day_limit, "日"),
        ]
        for key, ttl, limit, label in checks:
            count = int(self._redis.incr(key) or 0)
            if count == 1:
                self._redis.expire(key, ttl)
            if limit > 0 and count > limit:
                detail = {"scope": ctx.token_scope, "path": path, "window": label, "count": count, "limit": limit}
                self.record_security_event(
                    token_id=ctx.token_id,
                    user_id=ctx.user_id,
                    event_type="data_api_rate_limit_exceeded",
                    path=path,
                    detail=detail,
                )
                raise HTTPException(status_code=429, detail=f"超出{label}额度上限 {limit}")

    def current_request_id(self, token_id: str) -> str:
        return str(self._redis.get(f"data_api:concurrent:{token_id}") or "").strip()

    def _conflict_key(self, token_id: str) -> str:
        return f"data_api:concurrent:conflict:{token_id}"

    def _acquire_concurrent(self, ctx: AuthContext, path: str) -> str:
        key = f"data_api:concurrent:{ctx.token_id}"
        conflict_key = self._conflict_key(ctx.token_id)
        request_id = str(uuid.uuid4())
        script = """
        local current = redis.call('GET', KEYS[1])
        if current and current ~= '' and current ~= ARGV[1] then
          redis.call('SETEX', KEYS[2], tonumber(ARGV[2]), current)
          return current
        end
        redis.call('SET', KEYS[1], ARGV[1], 'EX', tonumber(ARGV[2]))
        redis.call('DEL', KEYS[2])
        return ARGV[1]
        """
        result = str(self._redis.eval(script, 2, key, conflict_key, request_id, CONCURRENT_KEY_TTL_SECONDS) or "").strip()
        if result == request_id:
            return request_id
        self.record_security_event(
            token_id=ctx.token_id,
            user_id=ctx.user_id,
            event_type="data_api_concurrent_limit_exceeded",
            path=path,
            detail={"limit": FORCED_MAX_CONCURRENT_PER_TOKEN, "active_request_id": result[:12]},
        )
        raise HTTPException(status_code=429, detail="检测到同一 Token 存在并发请求，系统已中止当前连接，请串行重试")

    def ensure_request_not_conflicted(self, ctx: AuthContext) -> None:
        if not ctx.active_request_id:
            return
        active_request_id = self.current_request_id(ctx.token_id)
        if active_request_id and active_request_id != ctx.active_request_id:
            raise HTTPException(status_code=429, detail="检测到同一 Token 存在并发请求，当前请求已中止")
        conflict_request_id = str(self._redis.get(self._conflict_key(ctx.token_id)) or "").strip()
        if conflict_request_id and conflict_request_id == ctx.active_request_id:
            self._redis.delete(self._conflict_key(ctx.token_id))
            raise HTTPException(status_code=429, detail="检测到同一 Token 存在并发请求，当前请求已中止")

    def _release_concurrent(self, ctx: AuthContext) -> None:
        if not ctx.active_request_id:
            return
        key = f"data_api:concurrent:{ctx.token_id}"
        script = """
        local cur = redis.call('GET', KEYS[1])
        if cur == ARGV[1] then redis.call('DEL', KEYS[1]) end
        return 1
        """
        try:
            self._redis.eval(script, 1, key, ctx.active_request_id)
        except Exception:
            logger.exception("release concurrent failed token_id=%s", ctx.token_id)

    def get_data_token_dependency(self, *, table_name: Optional[str] = None, count_usage: bool = True):
        def _dep(request: Request) -> Iterator[AuthContext]:
            token = extract_token_from_request(request)
            if not validate_token_format(token):
                raise HTTPException(status_code=401, detail="缺少或非法 Authorization Token")
            ctx = self.load_token_context(token)
            if not ctx:
                raise HTTPException(status_code=403, detail="Token 不存在")
            self._ensure_token_state(ctx)
            self._check_scope(ctx, self._settings.default_token_scope)
            self._check_allowed_tables(ctx, table_name)
            self._enforce_fingerprint(request, ctx)
            path = str(request.url.path)
            if count_usage:
                self._enforce_rate_limits(ctx, path)
            ctx.active_request_id = self._acquire_concurrent(ctx, path)
            try:
                yield ctx
            finally:
                self._release_concurrent(ctx)

        return _dep

    def get_admin_dashboard_dependency(self):
        def _dep(request: Request) -> AuthContext:
            token = extract_token_from_request(request)
            if not validate_token_format(token):
                raise HTTPException(status_code=401, detail="缺少或非法 Authorization Token")
            ctx = self.load_token_context(token)
            if not ctx:
                raise HTTPException(status_code=403, detail="Token 不存在")
            self._ensure_token_state(ctx)
            self._check_scope(ctx, "dashboard")
            self._check_admin(ctx)
            return ctx

        return _dep

    def get_data_admin_dependency(self):
        def _dep(request: Request) -> AuthContext:
            token = extract_token_from_request(request)
            if not validate_token_format(token):
                raise HTTPException(status_code=401, detail="缺少或非法 Authorization Token")
            ctx = self.load_token_context(token)
            if not ctx:
                raise HTTPException(status_code=403, detail="Token 不存在")
            self._ensure_token_state(ctx)
            self._check_scope(ctx, self._settings.default_token_scope)
            if not self.is_admin(ctx):
                raise HTTPException(status_code=403, detail="需要 data_api admin token")
            return ctx

        return _dep

    def ensure_user_exists(self, *, user_id: str = "", username: str = "", email: str = "") -> Dict[str, str]:
        with self._db.connection(readonly=False) as conn:
            with conn.cursor() as cur:
                if user_id:
                    cur.execute("SELECT id::text, username, COALESCE(email,'') FROM auth_user WHERE id=%s::uuid LIMIT 1", (user_id,))
                    row = cur.fetchone()
                    if row:
                        return {"user_id": str(row[0]), "username": str(row[1]), "email": str(row[2] or "")}
                    raise HTTPException(status_code=404, detail="user_id 不存在")
                if username:
                    cur.execute("SELECT id::text, username, COALESCE(email,'') FROM auth_user WHERE username=%s LIMIT 1", (username,))
                    row = cur.fetchone()
                    if row:
                        return {"user_id": str(row[0]), "username": str(row[1]), "email": str(row[2] or "")}
                    cur.execute(
                        """
                        INSERT INTO auth_user(id, username, email, status)
                        VALUES (%s, %s, %s, 1)
                        RETURNING id::text, username, COALESCE(email,'')
                        """,
                        (str(uuid.uuid4()), username, email),
                    )
                    created = cur.fetchone()
                    cur.execute("SELECT id::text FROM auth_role WHERE name='visitor' LIMIT 1")
                    role = cur.fetchone()
                    if role:
                        cur.execute(
                            """
                            INSERT INTO auth_user_role(user_id, role_id)
                            VALUES (%s::uuid, %s::uuid)
                            ON CONFLICT (user_id, role_id) DO NOTHING
                            """,
                            (created[0], role[0]),
                        )
                    return {"user_id": str(created[0]), "username": str(created[1]), "email": str(created[2] or "")}
        raise HTTPException(status_code=400, detail="必须提供 user_id 或 username")

    def ensure_seed_data_api_admin(self) -> Dict[str, str]:
        username = "data_api_admin"
        email = "data_api_admin@local"
        token_name = "data_api_super_admin"
        with self._db.connection(readonly=False) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id::text FROM auth_user WHERE username=%s LIMIT 1", (username,))
                row = cur.fetchone()
                if row:
                    user_id = str(row[0] or "").strip()
                else:
                    cur.execute(
                        """
                        INSERT INTO auth_user(id, username, email, status)
                        VALUES (%s, %s, %s, 1)
                        RETURNING id::text
                        """,
                        (str(uuid.uuid4()), username, email),
                    )
                    user_id = str(cur.fetchone()[0] or "").strip()

                cur.execute("SELECT id::text FROM auth_role WHERE name='admin' LIMIT 1")
                role_row = cur.fetchone()
                if role_row:
                    cur.execute(
                        """
                        INSERT INTO auth_user_role(user_id, role_id)
                        VALUES (%s::uuid, %s::uuid)
                        ON CONFLICT (user_id, role_id) DO NOTHING
                        """,
                        (user_id, str(role_row[0] or "").strip()),
                    )

                cur.execute(
                    """
                    SELECT id::text, token
                    FROM auth_token
                    WHERE user_id=%s::uuid
                      AND COALESCE(NULLIF(token_scope, ''), 'dashboard')=%s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (user_id, self._settings.default_token_scope),
                )
                token_row = cur.fetchone()
                if token_row:
                    token_id = str(token_row[0] or "").strip()
                    token_value = str(token_row[1] or "").strip()
                    cur.execute(
                        """
                        UPDATE auth_token
                        SET enabled=TRUE,
                            is_valid=TRUE,
                            restore_valid_at=NULL,
                            expires_at=NULL,
                            banned_until=NULL,
                            ban_reason=NULL,
                            ban_detail='{}'::jsonb,
                            name=%s,
                            token_scope=%s,
                            rate_limit_per_minute=-1,
                            rate_limit_per_hour=-1,
                            rate_limit_per_day=-1,
                            quota_max_concurrent=-1,
                            quota_max_queue=-1,
                            allowed_tables='[]'::jsonb,
                            fingerprint_binding_mode='disabled',
                            device_fingerprint_hash=NULL
                        WHERE id=%s::uuid
                        """,
                        (token_name, self._settings.default_token_scope, token_id),
                    )
                    return {"user_id": user_id, "token_id": token_id, "token": token_value}

                token_value = secrets.token_hex(32)
                cur.execute(
                    """
                    INSERT INTO auth_token(
                      id, token, user_id, enabled, is_valid, expires_at, name,
                      token_scope, rate_limit_per_minute, rate_limit_per_hour, rate_limit_per_day,
                      quota_max_concurrent, quota_max_queue, allowed_tables,
                      fingerprint_binding_mode, token_meta, issued_via, activated_at, last_status_changed_at
                    )
                    VALUES (
                      %s, %s, %s::uuid, TRUE, TRUE, NULL, %s,
                      %s, -1, -1, -1,
                      -1, -1, '[]'::jsonb,
                      'disabled', %s::jsonb, 'data_api_system_seed', NOW(), NOW()
                    )
                    RETURNING id::text
                    """,
                    (
                        str(uuid.uuid4()),
                        token_value,
                        user_id,
                        token_name,
                        self._settings.default_token_scope,
                        json.dumps({"seed": True, "scope": self._settings.default_token_scope}, ensure_ascii=False),
                    ),
                )
                token_id = str(cur.fetchone()[0] or "").strip()
        self.record_audit_event(
            token_id=token_id,
            user_id=user_id,
            event_type="token_issued",
            title="系统创建 data_api 管理员 Token",
            reason_code="data_api_admin_seed",
            detail={"scope": self._settings.default_token_scope, "token_name": token_name},
        )
        return {"user_id": user_id, "token_id": token_id, "token": token_value}
