"""Alembic env：data_query_service 专属。

关键：
- 从 FIN_POSTGRES_USER / FIN_POSTGRES_PASSWORD / FIN_POSTGRES_DATABASE 或
  system_config.yaml:database_server 拼接 DSN
- 用独立 version_table=alembic_version_data_query，避免与 24h_news（alembic_version_news）
  在同一 stock_data DB 内互相覆盖
"""
import os
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

VERSION_TABLE = "alembic_version_data_query"

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _resolve_database_url() -> str:
    """优先 env，次从 config/system_config.yaml 读 database_server。"""
    user = os.environ.get("FIN_POSTGRES_USER", "").strip()
    password = os.environ.get("FIN_POSTGRES_PASSWORD", "").strip()
    database = os.environ.get("FIN_POSTGRES_DATABASE", "").strip()
    host = os.environ.get("FIN_POSTGRES_HOST", "finsight_postgresql_timescale").strip()
    port = os.environ.get("FIN_POSTGRES_PORT", "5432").strip()

    if not (user and password and database):
        # 兜底：从 yaml
        try:
            import yaml  # type: ignore

            cfg_path = Path(__file__).resolve().parent.parent / "config" / "system_config.yaml"
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            db = cfg.get("database_server", {}) or {}
            user = user or str(db.get("user") or "").strip()
            password = password or str(db.get("password") or "").strip()
            database = database or str(db.get("database") or "").strip()
            host = str(db.get("host") or host).strip()
            port = str(db.get("port") or port).strip()
        except Exception:
            pass

    if not (user and password and database):
        raise RuntimeError(
            "无法拼接 DATABASE_URL：FIN_POSTGRES_{USER,PASSWORD,DATABASE} 环境变量缺失 "
            "且 config/system_config.yaml database_server 段也无值"
        )

    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"


config.set_main_option("sqlalchemy.url", _resolve_database_url())

target_metadata = None


def run_migrations_offline() -> None:
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
