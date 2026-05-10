"""
Stateless auth helpers —— 从 auth.py 抽出的纯函数工具。

这些函数不持有状态（不依赖 AuthService 实例 / redis / db），拆出到本文件让 auth.py
聚焦在 AuthContext + AuthService 主类上，降低单文件认知负担（861 → ~760 行）。

向后兼容：auth.py 顶部 `from ._auth_helpers import *` 保留，所有
`from app.auth import <helper>` 调用无需改动。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import Request

__all__ = [
    "validate_token_format",
    "extract_token_from_request",
    "client_ip",
    "mask_token",
    "bool_from_value",
    "datetime_from_value",
]


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
