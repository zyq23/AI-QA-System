"""Reliable background-job worker.

FastAPI BackgroundTasks are fire-and-forget: a crash between "response sent"
and "task executed" loses the work. This worker keeps the durable job state in
SQLite (see ``Repository.claim_job`` lease semantics) and executes registered
handlers with heartbeat, bounded retry and dead-lettering.

HTTP handlers enqueue work through the repository and then ask the worker to
run one job — either inline (dev/tests via BackgroundTasks adapter) or later
from a polling loop (``run_forever``). The adapter never re-implements job
bookkeeping: it always goes through claim/heartbeat/complete so the lease and
attempt columns stay truthful.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from app.repositories import Repository

logger = logging.getLogger(__name__)

JobHandler = Callable[[dict[str, Any], "JobContext"], None]


class JobCancelled(Exception):
    """Raised inside a running job when cancellation is observed."""


@dataclass
class JobContext:
    job_id: str
    owner: str
    payload: dict[str, Any]
    worker: "JobWorker"

    def cancelled(self) -> bool:
        return self.worker.repository.job_is_cancelled(self.job_id)

    def check_cancelled(self) -> None:
        if self.cancelled():
            raise JobCancelled(f"job {self.job_id} cancelled")

    def heartbeat(self) -> bool:
        return self.worker.repository.heartbeat_job(self.job_id, owner=self.owner)


class JobWorker:
    """Executes jobs by type with lease claim, heartbeat and retry/backoff."""

    def __init__(
        self,
        repository: Repository,
        *,
        owner: str,
        heartbeat_interval_seconds: int = 60,
        backoff_base_seconds: float = 5.0,
        max_backoff_seconds: float = 300.0,
    ) -> None:
        self.repository = repository
        self.owner = owner
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.backoff_base_seconds = backoff_base_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self._handlers: dict[str, JobHandler] = {}
        self._stop = threading.Event()

    def register(self, job_type: str, handler: JobHandler) -> None:
        self._handlers[job_type] = handler

    # -- single execution ---------------------------------------------------

    def run_one(self, job_id: str) -> str:
        """Claim and run one job. Returns the final status or 'skipped' when
        the lease could not be taken (already owned/terminal/cancelled)."""
        row = self.repository.get_job(job_id)
        if row is None:
            logger.warning("run_one: job %s not found", job_id)
            return "missing"
        handler = self._handlers.get(row["job_type"])
        if handler is None:
            self.repository.update_job(job_id, status="failed", message=f"no handler registered for {row['job_type']}")
            return "failed"

        claimed = self.repository.claim_job(job_id, owner=self.owner)
        if claimed is None:
            logger.debug("run_one: job %s not claimable (owner=%s)", job_id, self.owner)
            return "skipped"

        context = JobContext(job_id=job_id, owner=self.owner, payload=claimed["payload"], worker=self)
        stop_heartbeat = threading.Event()
        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(job_id, stop_heartbeat),
            daemon=True,
        )
        heartbeat_thread.start()
        try:
            handler(claimed["payload"], context)
        except JobCancelled as exc:
            logger.info("job %s cancelled mid-run: %s", job_id, exc)
            self.repository.update_job(job_id, status="cancelled", message=str(exc))
            return "cancelled"
        except Exception as exc:  # noqa: BLE001 - worker boundary
            logger.exception("job %s failed (attempt %s): %s", job_id, claimed["attempt"], exc)
            return self._handle_failure(job_id, claimed, exc)
        finally:
            stop_heartbeat.set()
            if heartbeat_thread.is_alive():
                heartbeat_thread.join(timeout=2.0)
        finished = self.repository.get_job(job_id)
        if finished and finished["status"] == "cancelled":
            return "cancelled"
        self.repository.complete_job(job_id, owner=self.owner, message="done")
        return "completed"

    def _handle_failure(self, job_id: str, claimed: dict[str, Any], exc: Exception) -> str:
        attempts_used = int(claimed["attempt"])
        attempts_cap = int(claimed.get("max_attempts") or 3)
        if attempts_used >= attempts_cap:
            self.repository.update_job(job_id, status="failed", message=f"attempts exhausted: {exc}")
            return "failed"
        backoff = min(self.max_backoff_seconds, self.backoff_base_seconds * (2 ** max(0, attempts_used - 1)))
        self.repository.requeue_job(job_id, message=f"retry {attempts_used}/{attempts_cap} after error: {exc}", not_before_seconds=backoff)
        return "requeued"

    def _heartbeat_loop(self, job_id: str, stop: threading.Event) -> None:
        while not stop.wait(self.heartbeat_interval_seconds):
            if not self.repository.heartbeat_job(job_id, owner=self.owner):
                logger.warning("heartbeat lost for job %s (owner=%s)", job_id, self.owner)
                return

    # -- polling loop -------------------------------------------------------

    def recover_stale(self, *, stale_after_seconds: int = 300) -> list[str]:
        """Requeue dead workers' jobs (lease lost) / dead-letter exhausted ones."""
        return self.repository.reclaim_stale_jobs(stale_after_seconds=stale_after_seconds)

    def tick(self, limit: int = 5) -> list[str]:
        """Claim and run up to ``limit`` queued jobs. Returns their outcomes."""
        outcomes: list[str] = []
        for job in self.repository.list_queued_jobs(limit=limit):
            outcomes.append(self.run_one(job["id"]))
        return outcomes

    def run_forever(self, *, poll_interval_seconds: float = 5.0) -> None:
        while not self._stop.is_set():
            try:
                self.recover_stale()
                outcomes = self.tick()
                if outcomes:
                    logger.info("worker tick finished jobs: %s", outcomes)
            except Exception:  # noqa: BLE001 - loop must survive transient errors
                logger.exception("worker tick failed")
            self._stop.wait(poll_interval_seconds)

    def stop(self) -> None:
        self._stop.set()
