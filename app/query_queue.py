from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from .config import Settings
from .snapshot_service import SnapshotResult, SnapshotService

logger = logging.getLogger(__name__)


class QueueSaturatedError(Exception):
    pass


@dataclass
class _PendingRefresh:
    future: asyncio.Future
    enqueued_by: str
    waiter_count: int = 0


class QueryQueueManager:
    def __init__(self, snapshot_service: SnapshotService, settings: Settings) -> None:
        self._snapshot_service = snapshot_service
        self._settings = settings
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=settings.query_queue_max_size)
        self._lock = asyncio.Lock()
        self._pending: Dict[str, _PendingRefresh] = {}
        self._token_waiters: Dict[str, int] = {}
        self._workers: List[asyncio.Task] = []
        self._warm_task: Optional[asyncio.Task] = None
        self._stopped = False

    async def start(self) -> None:
        for idx in range(self._settings.query_workers):
            self._workers.append(asyncio.create_task(self._worker(idx), name=f"data-api-queue-worker-{idx}"))
        self._warm_task = asyncio.create_task(self._periodic_refresh_loop(), name="data-api-warm-loop")

    async def stop(self) -> None:
        self._stopped = True
        for task in self._workers:
            task.cancel()
        if self._warm_task:
            self._warm_task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        if self._warm_task:
            await asyncio.gather(self._warm_task, return_exceptions=True)

    async def get_snapshot(self, *, table_name: str, token_id: str, max_queue: int) -> SnapshotResult:
        cached = self._snapshot_service.get_cached_snapshot(table_name)
        if cached:
            return cached
        safe_max_queue = max(1, int(max_queue or 1))
        async with self._lock:
            current_waiters = int(self._token_waiters.get(token_id, 0))
            if current_waiters >= safe_max_queue:
                raise QueueSaturatedError(f"当前 token 等待队列已满（上限 {safe_max_queue}）")
            self._token_waiters[token_id] = current_waiters + 1

            pending = self._pending.get(table_name)
            if pending is None:
                if self._queue.full():
                    self._token_waiters[token_id] = max(0, self._token_waiters.get(token_id, 1) - 1)
                    raise QueueSaturatedError("全局刷新队列已满，请稍后重试")
                loop = asyncio.get_running_loop()
                pending = _PendingRefresh(future=loop.create_future(), enqueued_by=token_id, waiter_count=0)
                self._pending[table_name] = pending
                await self._queue.put(table_name)
            pending.waiter_count += 1

        try:
            return await asyncio.wait_for(pending.future, timeout=self._settings.query_wait_timeout_seconds)
        finally:
            async with self._lock:
                self._token_waiters[token_id] = max(0, self._token_waiters.get(token_id, 1) - 1)
                if self._token_waiters[token_id] == 0:
                    self._token_waiters.pop(token_id, None)

    async def _worker(self, idx: int) -> None:
        while not self._stopped:
            table_name = await self._queue.get()
            try:
                snapshot = await asyncio.wait_for(
                    asyncio.to_thread(self._snapshot_service.refresh_snapshot, table_name),
                    timeout=self._settings.query_job_timeout_seconds,
                )
                await self._resolve_pending(table_name, snapshot, None)
            except Exception as exc:
                logger.exception("refresh snapshot failed worker=%s table=%s", idx, table_name)
                await self._resolve_pending(table_name, None, exc)
            finally:
                self._queue.task_done()

    async def _resolve_pending(self, table_name: str, snapshot: Optional[SnapshotResult], exc: Optional[Exception]) -> None:
        async with self._lock:
            pending = self._pending.pop(table_name, None)
        if not pending:
            return
        if pending.future.done():
            return
        if exc is not None:
            pending.future.set_exception(exc)
        else:
            pending.future.set_result(snapshot)

    async def _periodic_refresh_loop(self) -> None:
        await asyncio.sleep(0.5)
        while not self._stopped:
            for table_name in self._snapshot_service.list_supported_tables():
                try:
                    await asyncio.to_thread(self._snapshot_service.refresh_snapshot, table_name)
                except Exception:
                    logger.exception("periodic refresh failed table=%s", table_name)
            await asyncio.sleep(self._settings.cache_refresh_interval_seconds)

    def runtime_status(self) -> Dict[str, object]:
        return {
            "queue_size": self._queue.qsize(),
            "queue_capacity": self._settings.query_queue_max_size,
            "pending_tables": list(self._pending.keys()),
            "token_waiters": dict(self._token_waiters),
            "workers": len(self._workers),
        }
