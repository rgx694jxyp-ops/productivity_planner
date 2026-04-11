"""Job scaffolding types.

Synchronous execution is the only runtime mode today. The `run_mode` field is
kept on requests so call sites do not need to change when async backends are
introduced later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class JobRequest:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    run_mode: str = "sync"  # accepted values: "sync", "async"
    backend: str = "inline"


@dataclass(frozen=True)
class JobMeta:
    job_id: str
    name: str
    requested_mode: str
    executed_mode: str
    backend: str
    duration_ms: int
