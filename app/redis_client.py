from __future__ import annotations

import logging

import redis

from .config import Settings

logger = logging.getLogger(__name__)


def build_redis(settings: Settings) -> redis.Redis:
    client = redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        password=settings.redis_password or None,
        decode_responses=settings.redis_decode_responses,
        socket_timeout=settings.redis_socket_timeout,
        socket_connect_timeout=settings.redis_socket_connect_timeout,
        retry_on_timeout=settings.redis_retry_on_timeout,
        health_check_interval=settings.redis_health_check_interval,
        max_connections=settings.redis_max_connections,
    )
    client.ping()
    logger.info("redis connected host=%s port=%s db=%s", settings.redis_host, settings.redis_port, settings.redis_db)
    return client
