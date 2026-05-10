# data_query_service Schema Migrations (Alembic)

本服务的 DB schema 变更**必须**走 alembic。这是 stock_system 集群的第 2 个 alembic 化服务（继 24h_news 之后），关闭上层 [`../../stock_system/AGENTS.md §7 红1`](../AGENTS.md) 的 data_query_service 部分。

## 工作机制

- `alembic.ini` + `alembic/env.py`：env.py 从 `FIN_POSTGRES_USER / FIN_POSTGRES_PASSWORD / FIN_POSTGRES_DATABASE` 等环境变量（docker-compose 注入）或 `config/system_config.yaml:database_server` 自动拼接 DSN，转换为 `postgresql+psycopg2://`（alembic 用同步驱动，业务运行时仍用 psycopg2 pool）
- `alembic/versions/`：migration 脚本（按 revision 号排序）
- 容器启动时 `start.py:_run_alembic_upgrade()` 自动跑 `alembic upgrade head`，schema 失败**硬阻塞启动**（避免 schema 与代码错配跑业务）
- 紧急绕过：`SKIP_ALEMBIC_UPGRADE=1` 环境变量（仅 debug）

## ⚠️ 多服务共享 DB 的 version_table 隔离

`stock_data` DB 被 `24h_news` 和 `data_query_service` 共用（以及未来 `real_time_analyse` / `update_data` 迁移后的服务）。alembic 默认用单一 `alembic_version` 表会导致服务间互相覆盖 version_num。

**本服务 env.py 强制设置** `version_table="alembic_version_data_query"`（见 `alembic/env.py:VERSION_TABLE`）。任何未来在同一 DB 上跑 alembic 的服务**必须**用独立 version_table：

- `alembic_version_news`（24h_news）
- `alembic_version_data_query`（本服务）
- 未来：`alembic_version_analyse` / `alembic_version_update`

## 当前 baseline

- **V001**：`alembic/versions/001_baseline_auth_schema.py` —— 完整复用原 `app/schema.py:SCHEMA_SQL`，含：
  - `CREATE EXTENSION IF NOT EXISTS pgcrypto`
  - 7 张 auth_* 表（user / role / user_role / token / user_role / security_event / token_audit_log）
  - `auth_token` 的 12 个 `ADD COLUMN IF NOT EXISTS`（scope / rate_limit / quota / fingerprint 等）
  - 3 个 `CREATE INDEX IF NOT EXISTS`
  - 初始 role 数据（admin / visitor）`ON CONFLICT DO NOTHING`
  - **完全幂等**，既有 DB 直接 `upgrade head` NO-OP 通过

## 加新列 / 索引 / 类型变更

```bash
# 1. 创建 revision 骨架
docker exec api-data_query alembic revision -m "add auth_token.<column>"

# 2. 编辑 alembic/versions/<rev>_*.py 写 upgrade/downgrade
#    - 普通 schema 改动：op.add_column / op.alter_column / op.create_index
#    - 复杂 SQL（CTE / window / trigger）：op.execute("...")
#    - 必须保证幂等（IF NOT EXISTS / 参考 V001 模式）

# 3. 本地验证（建议 upgrade → downgrade → upgrade 三轮）
docker exec api-data_query alembic upgrade head
docker exec api-data_query alembic current
docker exec api-data_query alembic downgrade -1
docker exec api-data_query alembic upgrade head

# 4. commit + push
cd data_query_service && git add alembic/versions/<rev>_*.py
git commit -m "[1.x.y]feat: <描述> (alembic V<rev>)"
git push
```

## 模板：加列 + 索引

```python
"""add auth_token.last_used_ip

Revision ID: 002
Revises: 001
Create Date: 2026-05-15
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "auth_token",
        sa.Column("last_used_ip", sa.Text, nullable=True),
    )
    op.create_index(
        "idx_auth_token_last_used_ip",
        "auth_token",
        ["last_used_ip"],
    )


def downgrade() -> None:
    op.drop_index("idx_auth_token_last_used_ip", table_name="auth_token")
    op.drop_column("auth_token", "last_used_ip")
```

## 检查当前 schema 版本

```bash
docker exec api-data_query alembic current
# 期望：001 (head)
```

直接查 DB：

```bash
docker exec finsight_postgresql_timescale \
    psql -U user_admin -d stock_data -c "SELECT version_num FROM alembic_version_data_query;"
```

## app/schema.py 状态

`app/schema.py` 已**部分 DEPRECATED**（2026-05-10）：
- `SCHEMA_SQL` + `ensure_schema()`：不再被 `main.py` 调用，保留 ~2 周观察期后独立 commit 删除
- `normalize_allowed_tables()` 函数：仍被 `app/auth.py` 引用，继续保留（非 schema 相关）

## 故障排查

| 症状 | 原因 | 修复 |
|---|---|---|
| 启动报 `无法拼接 DATABASE_URL` | FIN_POSTGRES_{USER,PASSWORD,DATABASE} 未注入 | 检查 `api-service.yml` 的 environment 段 + stock_system/.env |
| 启动报 `relation "alembic_version_data_query" does not exist` | DB 新建后没跑过 upgrade | 重启容器会自动跑；或手动 `docker exec api-data_query alembic upgrade head` |
| 两服务 alembic 互相覆盖 version | env.py 未设 version_table | 检查 `alembic/env.py:VERSION_TABLE` 是本服务专属 |
| alembic 升级卡住 | 连接池耗尽 / 长事务冲突 | `docker compose restart api-data_query` 释放；紧急用 `SKIP_ALEMBIC_UPGRADE=1` |

## 跨服务 alembic 化进度（红1 关闭判据）

- [x] 24h_news（v1.3.0，alembic_version_news）
- [x] data_query_service（本服务，v1.3.0，alembic_version_data_query）
- [ ] real_time_analyse（与 update_data 共用 `*/utils/structural_maintenance.py`，独立立项）
- [ ] update_data（同上）

每个服务自己一份 alembic（不跨服务统一，符合 [`../../AGENTS.md §8 微服务边界`](../AGENTS.md)）。
