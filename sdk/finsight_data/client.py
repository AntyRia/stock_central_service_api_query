from __future__ import annotations

import base64
from typing import Iterable, Optional

import requests

from . import __version__
from .fingerprint import build_device_fingerprint

_DEFAULT_BASE_URL_OBF = "Dh0aA1NIR0RJAAxfElAeXRMNElleFhYdDwoLXQoJRxBMBwU0BxkH"
_DEFAULT_BASE_URL_KEY = b"finsight-sdk"


def _decode_default_base_url() -> str:
    raw = base64.urlsafe_b64decode(_DEFAULT_BASE_URL_OBF.encode("utf-8"))
    return bytes(item ^ _DEFAULT_BASE_URL_KEY[index % len(_DEFAULT_BASE_URL_KEY)] for index, item in enumerate(raw)).decode("utf-8")


class FinSightDataClient:
    """FinSight read-only data API client."""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        token: str,
        timeout: int = 20,
        device_fingerprint: Optional[str] = None,
    ) -> None:
        self.base_url = (base_url or _decode_default_base_url()).rstrip("/")
        self.token = token.strip()
        self.timeout = timeout
        self.device_fingerprint = device_fingerprint or build_device_fingerprint()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.token}",
                "X-Device-Fingerprint": self.device_fingerprint,
                "X-Client-Version": f"finsight-data/{__version__}",
            }
        )

    def _get(self, path: str, *, params: Optional[dict] = None, allow_rebind: bool = False) -> dict:
        merged_params = dict(params or {})
        if allow_rebind:
            merged_params["allow_rebind"] = "true"
        headers = {"X-Allow-Device-Rebind": "true"} if allow_rebind else None
        resp = self.session.get(f"{self.base_url}{path}", params=merged_params, headers=headers, timeout=self.timeout)
        if not resp.ok:
            try:
                payload = resp.json()
            except Exception:
                payload = resp.text
            detail = payload.get("detail") if isinstance(payload, dict) else str(payload)
            raise RuntimeError(f"HTTP {resp.status_code}: {detail}")
        return resp.json()

    @staticmethod
    def _join_codes(codes: Optional[Iterable[str]]) -> str:
        if not codes:
            return ""
        return ",".join(str(item).strip() for item in codes if str(item).strip())

    def get_stock_sector_fund_flow_daily_latest(
        self,
        *,
        board_type: str = "",
        keyword: str = "",
        limit: Optional[int] = None,
        offset: int = 0,
        allow_rebind: bool = False,
    ) -> dict:
        """Fetch latest-trade-day sector fund flow rows."""
        params = {"board_type": board_type, "keyword": keyword, "offset": offset}
        if limit is not None:
            params["limit"] = limit
        return self._get(
            "/api/data/latest/stock_sector_fund_flow_daily",
            params=params,
            allow_rebind=allow_rebind,
        )

    def get_stock_individual_fund_flow_daily_latest(
        self,
        *,
        codes: Optional[Iterable[str]] = None,
        keyword: str = "",
        limit: Optional[int] = None,
        offset: int = 0,
        allow_rebind: bool = False,
    ) -> dict:
        """Fetch latest-trade-day individual stock fund flow rows."""
        params = {"codes": self._join_codes(codes), "keyword": keyword, "offset": offset}
        if limit is not None:
            params["limit"] = limit
        return self._get(
            "/api/data/latest/stock_individual_fund_flow_daily",
            params=params,
            allow_rebind=allow_rebind,
        )

    def get_stock_daily_kline_q_latest(
        self,
        *,
        codes: Optional[Iterable[str]] = None,
        keyword: str = "",
        limit: Optional[int] = None,
        offset: int = 0,
        allow_rebind: bool = False,
    ) -> dict:
        """Fetch latest-trade-day full-market qfq daily kline rows."""
        params = {"codes": self._join_codes(codes), "keyword": keyword, "offset": offset}
        if limit is not None:
            params["limit"] = limit
        return self._get(
            "/api/data/latest/stock_daily_kline_q",
            params=params,
            allow_rebind=allow_rebind,
        )

    def get_token_usage(self, *, allow_rebind: bool = False) -> dict:
        """Fetch user-facing token quota usage and remaining balances."""
        return self._get("/api/token/usage", allow_rebind=allow_rebind)
