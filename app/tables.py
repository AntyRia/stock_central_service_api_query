from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping


@dataclass(frozen=True)
class TableDefinition:
    name: str
    order_by: str
    code_column: str = "code"
    name_column: str = "name"
    public_columns: tuple[str, ...] = ()
    public_aliases: Dict[str, str] = field(default_factory=dict)

    def project_row(self, row: Mapping[str, Any]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        for column in self.public_columns:
            target = self.public_aliases.get(column, column)
            payload[target] = row.get(column)
        return payload


TABLES: Dict[str, TableDefinition] = {
    "stock_sector_fund_flow_daily": TableDefinition(
        name="stock_sector_fund_flow_daily",
        order_by="main_net_inflow_amount DESC NULLS LAST, code ASC",
        public_columns=(
            "code",
            "name",
            "type",
            "pct_chg",
            "main_net_inflow_amount",
            "main_net_inflow_ratio",
            "super_large_net_inflow_amount",
            "super_large_net_inflow_ratio",
            "large_net_inflow_amount",
            "large_net_inflow_ratio",
            "medium_net_inflow_amount",
            "medium_net_inflow_ratio",
            "small_net_inflow_amount",
            "small_net_inflow_ratio",
            "main_net_inflow_top_stock",
        ),
        public_aliases={"type": "board_type"},
    ),
    "stock_individual_fund_flow_daily": TableDefinition(
        name="stock_individual_fund_flow_daily",
        order_by="main_net_inflow_amount DESC NULLS LAST, code ASC",
        public_columns=(
            "code",
            "name",
            "latest_price",
            "pct_chg",
            "main_net_inflow_amount",
            "main_net_inflow_ratio",
            "super_large_net_inflow_amount",
            "super_large_net_inflow_ratio",
            "large_net_inflow_amount",
            "large_net_inflow_ratio",
            "medium_net_inflow_amount",
            "medium_net_inflow_ratio",
            "small_net_inflow_amount",
            "small_net_inflow_ratio",
        ),
    ),
    "stock_daily_kline_q": TableDefinition(
        name="stock_daily_kline_q",
        order_by="amount DESC NULLS LAST, code ASC",
        public_columns=(
            "code",
            "open_price",
            "close_price",
            "high_price",
            "low_price",
            "volume",
            "amount",
            "amplitude",
            "change_amount",
            "pctchg",
            "turnover_rate",
        ),
        public_aliases={"pctchg": "pct_chg"},
    ),
}
