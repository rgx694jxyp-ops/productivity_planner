"""Minimal job runner.

Design notes:
- Sync now: all operations execute inline in-process for local development.
- Async later: `JobRequest.run_mode` and backend selection are already modeled,
  so call sites can remain unchanged when a queue backend is added.
"""

from __future__ import annotations

import time
import uuid
from typing import Callable, TypeVar

from jobs.types import JobMeta, JobRequest

T = TypeVar("T")


class InlineBackend:
    """Local-development backend that runs jobs immediately in the caller thread."""

    name = "inline"

    def execute(self, operation: Callable[[], T]) -> T:
        return operation()


class JobRunner:
    def __init__(self) -> None:
        self._inline_backend = InlineBackend()

    def execute(self, request: JobRequest, operation: Callable[[], T]) -> tuple[T, JobMeta]:
        run_mode = str(request.run_mode or "sync").strip().lower() or "sync"
        if run_mode not in {"sync", "async"}:
            raise ValueError(f"Unsupported run_mode: {run_mode}")

        # Async is intentionally not implemented yet. We execute inline for now
        # but preserve requested mode for compatibility and migration planning.
        executed_mode = "sync"

        start = time.perf_counter()
        result = self._inline_backend.execute(operation)
        duration_ms = int((time.perf_counter() - start) * 1000)

        meta = JobMeta(
            job_id=str(uuid.uuid4()),
            name=request.name,
            requested_mode=run_mode,
            executed_mode=executed_mode,
            backend=self._inline_backend.name,
            duration_ms=duration_ms,
        )
        return result, meta


_default_runner = JobRunner()


def execute_job_with_meta(request: JobRequest, operation: Callable[[], T]) -> tuple[T, JobMeta]:
    return _default_runner.execute(request, operation)


def execute_job(request: JobRequest, operation: Callable[[], T]) -> T:
    result, _meta = execute_job_with_meta(request, operation)
    return result
