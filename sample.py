from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    STATUS   = "status"
    PROGRESS = "progress"
    RESULT   = "result"
    ERROR    = "error"


class StatusState(str, Enum):
    STARTED   = "started"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"


# ---------------------------------------------------------------------------
# Individual event payloads
# ---------------------------------------------------------------------------

class StatusEvent(BaseModel):
    type: Literal[EventType.STATUS] = EventType.STATUS
    state: StatusState
    message: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ProgressEvent(BaseModel):
    type: Literal[EventType.PROGRESS] = EventType.PROGRESS
    step: int
    total: int
    label: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    @property
    def percent(self) -> float:
        return round(self.step / self.total * 100, 1) if self.total else 0.0


class ResultEvent(BaseModel):
    type: Literal[EventType.RESULT] = EventType.RESULT
    payload: dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ErrorEvent(BaseModel):
    type: Literal[EventType.ERROR] = EventType.ERROR
    code: int
    detail: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Discriminated union — one type that covers every possible event
# ---------------------------------------------------------------------------

SSEEvent = Annotated[
    Union[StatusEvent, ProgressEvent, ResultEvent, ErrorEvent],
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Wire envelope
# ---------------------------------------------------------------------------

class SSEMessage(BaseModel):
    """
    Serialised to the raw SSE wire format:

        event: <event_type>
        data:  <json payload>
        id:    <optional message id>

    """
    event: EventType
    data: SSEEvent
    id: str | None = None

    def to_sse_bytes(self) -> bytes:
        lines: list[str] = []
        if self.id:
            lines.append(f"id: {self.id}")
        lines.append(f"event: {self.event.value}")
        lines.append(f"data: {self.data.model_dump_json()}")
        lines.append("\n")          # blank line terminates the message
        return "\n".join(lines).encode()



"""
service.py — business logic layer.

All methods are plain generators that yield SSEMessage objects.
They are intentionally framework-agnostic; the view layer is
responsible for serialising them onto the HTTP response.
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Generator

from .models import (
    ErrorEvent,
    EventType,
    ProgressEvent,
    ResultEvent,
    SSEMessage,
    StatusEvent,
    StatusState,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _msg(event: EventType, data, *, msg_id: str | None = None) -> SSEMessage:
    return SSEMessage(event=event, data=data, id=msg_id or str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------

def run_job_stream(job_id: str) -> Generator[SSEMessage, None, None]:
    """
    Simulate a multi-step background job and stream its progress.

    Replace the `time.sleep` calls and mock payloads with your real logic
    (DB queries, ML inference, external API calls, etc.).
    """
    steps = [
        "Validating input",
        "Fetching data from source",
        "Running transformation",
        "Persisting results",
        "Generating report",
    ]
    total = len(steps)

    # 1. Announce start
    yield _msg(
        EventType.STATUS,
        StatusEvent(state=StatusState.STARTED, message=f"Job {job_id} accepted"),
    )
    time.sleep(0.3)

    # 2. Stream progress, one step at a time
    for i, label in enumerate(steps, start=1):
        yield _msg(
            EventType.PROGRESS,
            ProgressEvent(step=i, total=total, label=label),
        )
        time.sleep(0.5)   # ← swap with real async I/O if using async Django / ASGI

    # 3. Emit the final result payload
    yield _msg(
        EventType.RESULT,
        ResultEvent(
            payload={
                "job_id": job_id,
                "records_processed": 1_024,
                "output_url": f"/results/{job_id}/report.csv",
            }
        ),
    )
    time.sleep(0.1)

    # 4. Signal completion
    yield _msg(
        EventType.STATUS,
        StatusEvent(state=StatusState.COMPLETED, message="Job finished successfully"),
    )


def run_job_stream_with_error(job_id: str) -> Generator[SSEMessage, None, None]:
    """Same as above but simulates a mid-job failure — useful for testing."""
    yield _msg(
        EventType.STATUS,
        StatusEvent(state=StatusState.STARTED, message=f"Job {job_id} accepted"),
    )
    time.sleep(0.3)

    yield _msg(
        EventType.PROGRESS,
        ProgressEvent(step=1, total=5, label="Validating input"),
    )
    time.sleep(0.4)

    # Something goes wrong on step 2
    yield _msg(
        EventType.ERROR,
        ErrorEvent(code=422, detail="Source schema mismatch on column 'amount'"),
    )
    yield _msg(
        EventType.STATUS,
        StatusEvent(state=StatusState.FAILED, message="Job aborted"),
    )


"""
views.py — Django streaming endpoint.

Routing (urls.py):

    from django.urls import path
    from .views import JobStreamView

    urlpatterns = [
        path("api/jobs/<str:job_id>/stream/", JobStreamView.as_view(), name="job-stream"),
        path("api/jobs/<str:job_id>/stream/error/", JobStreamView.as_view(), {"simulate_error": True}),
    ]

Requirements:
    pip install django pydantic
"""
from __future__ import annotations

from collections.abc import Generator

from django.http import StreamingHttpResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .models import SSEMessage
from .service import run_job_stream, run_job_stream_with_error


# ---------------------------------------------------------------------------
# Low-level SSE helpers
# ---------------------------------------------------------------------------

_HEARTBEAT = b": heartbeat\n\n"   # keeps the TCP connection alive through proxies


def _sse_stream(
    generator: Generator[SSEMessage, None, None],
    *,
    heartbeat_every: int = 5,
) -> Generator[bytes, None, None]:
    """
    Wrap a service-level generator and convert each SSEMessage to raw bytes.

    Yields a heartbeat comment every `heartbeat_every` messages so that
    reverse proxies (nginx, AWS ALB …) don't time out the connection.
    """
    for i, message in enumerate(generator):
        yield message.to_sse_bytes()
        if i % heartbeat_every == 0:
            yield _HEARTBEAT


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------

@method_decorator(csrf_exempt, name="dispatch")   # remove if you use token auth
class JobStreamView(View):
    """
    GET /api/jobs/<job_id>/stream/

    Streams Server-Sent Events for the given job.

    Response headers set automatically:
        Content-Type: text/event-stream
        Cache-Control: no-cache
        X-Accel-Buffering: no   ← disables nginx proxy buffering
    """

    http_method_names = ["get"]

    def get(self, request, job_id: str, simulate_error: bool = False):
        generator = (
            run_job_stream_with_error(job_id)
            if simulate_error
            else run_job_stream(job_id)
        )

        response = StreamingHttpResponse(
            streaming_content=_sse_stream(generator),
            content_type="text/event-stream",
        )
        response["Cache-Control"]    = "no-cache"
        response["X-Accel-Buffering"] = "no"     # nginx: disable proxy buffering
        return response
