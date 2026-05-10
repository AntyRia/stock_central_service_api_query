import logging
import os

import uvicorn

logger = logging.getLogger("start")


def _run_alembic_upgrade() -> None:
    """
    启动前跑 alembic upgrade head（幂等：V001 全 IF NOT EXISTS）。

    失败硬阻塞启动 —— schema 与代码强绑定，不允许错配跑业务。
    紧急绕过：SKIP_ALEMBIC_UPGRADE=1（仅 debug）。
    """
    if os.getenv("SKIP_ALEMBIC_UPGRADE", "").strip() in {"1", "true", "TRUE", "yes", "YES"}:
        logger.warning("SKIP_ALEMBIC_UPGRADE 已开启，跳过 alembic upgrade head")
        return

    from alembic import command
    from alembic.config import Config

    cfg = Config("/app/alembic.ini")
    # env.py 从 FIN_POSTGRES_* / system_config.yaml 自动解析 DSN
    logger.info("运行 alembic upgrade head ...")
    command.upgrade(cfg, "head")
    logger.info("alembic upgrade head 完成")


def main() -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    _run_alembic_upgrade()

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    uvicorn.run("app.main:app", host=host, port=port, reload=False, log_level="info")


if __name__ == "__main__":
    main()
