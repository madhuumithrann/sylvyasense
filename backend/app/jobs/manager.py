"""Asynchronous job orchestration.

Analysis takes seconds, not milliseconds, so it runs off the request thread and
the UI polls for state. The job record carries the *real* per-step state
reported by the pipeline — there is no synthetic percentage anywhere. Progress
is expressed as completed steps out of total steps, which is a fact; within a
step the UI is expected to show an indeterminate indicator.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.analysis.pipeline import STEPS, StepState
from app.core.config import get_settings
from app.core.errors import SylvaSenseError, internal

log = logging.getLogger("sylvasense.jobs")


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


@dataclass
class JobStep:
    key: str
    label: str
    state: StepState = StepState.PENDING
    note: str = ""
    started_at: str | None = None
    finished_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "state": self.state.value,
            "note": self.note,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass
class Job:
    job_id: str
    kind: str
    status: JobStatus = JobStatus.QUEUED
    steps: list[JobStep] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    )
    started_at: str | None = None
    finished_at: str | None = None
    error: dict[str, Any] | None = None
    result_ref: dict[str, Any] | None = None
    context: dict[str, Any] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            done = sum(
                1
                for s in self.steps
                if s.state in (StepState.DONE, StepState.SKIPPED)
            )
            return {
                "job_id": self.job_id,
                "kind": self.kind,
                "status": self.status.value,
                "steps": [s.as_dict() for s in self.steps],
                "steps_completed": done,
                "steps_total": len(self.steps),
                "created_at": self.created_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "error": self.error,
                "result": self.result_ref,
                "context": self.context,
            }

    def report(self, key: str, state: StepState, note: str) -> None:
        stamp = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
        with self._lock:
            for step in self.steps:
                if step.key != key:
                    continue
                step.state = state
                if note:
                    step.note = note
                if state == StepState.ACTIVE:
                    step.started_at = stamp
                elif state in (StepState.DONE, StepState.SKIPPED, StepState.FAILED):
                    step.finished_at = stamp
                return


class JobManager:
    def __init__(self) -> None:
        settings = get_settings()
        self._pool = ThreadPoolExecutor(
            max_workers=max(settings.max_concurrent_jobs, 1),
            thread_name_prefix="sylvasense-job",
        )
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    def create(
        self, kind: str, steps: list[tuple[str, str]] | None = None, **context: Any
    ) -> Job:
        job = Job(
            job_id=uuid.uuid4().hex[:12],
            kind=kind,
            steps=[JobStep(key=k, label=label) for k, label in (steps or list(STEPS))],
            context=context,
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._order.append(job.job_id)
            while len(self._order) > 200:
                stale = self._order.pop(0)
                self._jobs.pop(stale, None)
        return job

    def submit(self, job: Job, work: Callable[[Job], dict[str, Any]]) -> Job:
        def runner() -> None:
            job.status = JobStatus.RUNNING
            job.started_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
            try:
                job.result_ref = work(job)
                job.status = JobStatus.COMPLETE
            except SylvaSenseError as exc:
                job.error = exc.to_payload()["error"]
                job.status = JobStatus.FAILED
                self._mark_active_failed(job, exc.title)
                log.warning("Job %s failed: %s", job.job_id, exc.code)
            except Exception as exc:  # pragma: no cover — defensive
                detail = f"{type(exc).__name__}: {exc}"
                job.error = internal(detail).to_payload()["error"]
                job.status = JobStatus.FAILED
                self._mark_active_failed(job, "Unexpected internal error")
                log.error("Job %s crashed: %s\n%s", job.job_id, detail, traceback.format_exc())
            finally:
                job.finished_at = dt.datetime.now(dt.UTC).isoformat(
                    timespec="seconds"
                )

        self._pool.submit(runner)
        return job

    @staticmethod
    def _mark_active_failed(job: Job, note: str) -> None:
        for step in job.steps:
            if step.state == StepState.ACTIVE:
                step.state = StepState.FAILED
                step.note = note

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def stats(self) -> dict[str, int]:
        with self._lock:
            counts: dict[str, int] = {}
            for job in self._jobs.values():
                counts[job.status.value] = counts.get(job.status.value, 0) + 1
            counts["total"] = len(self._jobs)
            return counts


MANAGER = JobManager()
