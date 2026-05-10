"""Alembic env：从 FIN_POSTGRES_* 环境变量动态拼接 DSN。

本服务的 DB 配置走 FIN_POSTGRES_USER / FIN_POSTGRES_PASSWORD / FIN_POSTGRES_DATABASE
（docker-compose 通过 api-service.yml 注入，与 stock_system/.env 同源）。

与 24h_news 的 DATABASE_URL 方式不同，但最终效果一致：为 alembic 提供
postgresql+psycopg2:// DSN。

**关键**：本服务与 24h_news 共用同一个 PG DB（stock_data），必须用
version_table="alembic_version_data_query" 避免与 24h_news 冲突
（24h_news 用 alembic_version_news）。详见 ../../../AGENTS.md §4.2。
"""
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _build_runtime_dsn() -> str:
    """从 FIN_POSTGRES_* 环境变量拼接 alembic 用的同步 DSN"""
    host = (os.environ.get("FIN_POSTGRES_HOST") or "finsight_postgresql_timescale").strip()
    port = int(os.environ.get("FIN_POSTGRES_PORT") or 5432)
    db = (os.environ.get("FIN_POSTGRES_DATABASE") or "stock_data").strip()
    user = (os.environ.get("FIN_POSTGRES_USER") or "").strip()
    password = (os.environ.get("FIN_POSTGRES_PASSWORD") or "").strip()
    if not user or not password:
        raise RuntimeError(
            "alembic 需要 FIN_POSTGRES_USER 和 FIN_POSTGRES_PASSWORD 环境变量"
            "（docker-compose 通过 api-service.yml 从 stock_system/.env 注入）"
        )
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"


_runtime_url = _build_runtime_dsn()
config.set_main_option("sqlalchemy.url", _runtime_url)

# 本项目无 SQLAlchemy ORM 模型，所有 migration 走 op.execute()
target_metadata = None

# 共用 PG DB 时必须的隔离表名（详见 ../../../AGENTS.md §4.2）
VERSION_TABLE = "alembic_version_data_query"


def run_migrations_offline() -> None:
    """Offline 模式：仅生成 SQL 字符串（不连 DB）"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=VERSION_TABLE,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Online 模式（默认）：连 DB 执行 migration"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=VERSION_TABLE,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
