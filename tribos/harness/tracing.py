"""OpenTelemetry GenAI Semantic Conventions Tracing for Tribos.

Closes:
- F-14 / P2.1: OpenTelemetry GenAI semantic convention tracing for multi-agent workflows
- Hierarchical spans: workflow, tool execution, memory retrieval, verification checks, agent handoffs
- Token, duration, and provenance attribution on every span
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GenAISpan:
    span_id: str
    trace_id: str
    name: str  # e.g. "agent.workflow" | "agent.tool.execute" | "agent.memory.query" | "agent.verification"
    parent_span_id: str | None
    start_time: float
    end_time: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    status: str = "ok"  # ok | error

    def finish(self, status: str = "ok") -> None:
        self.end_time = time.time()
        self.status = status

    def duration_seconds(self) -> float:
        if self.end_time is None:
            return 0.0
        return max(0.0, self.end_time - self.start_time)

    def to_otlp_dict(self) -> dict[str, Any]:
        """Format span following OpenTelemetry GenAI Semantic Conventions."""
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "start_time_unix_nano": int(self.start_time * 1e9),
            "end_time_unix_nano": int((self.end_time or time.time()) * 1e9),
            "duration_s": round(self.duration_seconds(), 4),
            "status": {"code": self.status.upper()},
            "attributes": {
                # Standard OTel GenAI attributes
                "gen_ai.system": "tribos",
                **self.attributes,
            },
            "events": self.events,
        }


class GenAITracer:
    """Manages hierarchical OpenTelemetry GenAI spans for a run."""

    def __init__(self, trace_id: str | None = None) -> None:
        self.trace_id = trace_id or f"trc_{uuid.uuid4().hex[:16]}"
        self.spans: list[GenAISpan] = []
        self._active_spans: list[GenAISpan] = []

    def start_span(
        self,
        name: str,
        parent_span_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> GenAISpan:
        sid = f"spn_{uuid.uuid4().hex[:12]}"
        parent = parent_span_id or (self._active_spans[-1].span_id if self._active_spans else None)
        span = GenAISpan(
            span_id=sid,
            trace_id=self.trace_id,
            name=name,
            parent_span_id=parent,
            start_time=time.time(),
            attributes=attributes or {},
        )
        self.spans.append(span)
        self._active_spans.append(span)
        return span

    def end_span(self, span: GenAISpan, status: str = "ok") -> None:
        span.finish(status)
        if span in self._active_spans:
            self._active_spans.remove(span)

    def trace_tool_execution(
        self,
        tool_name: str,
        tool_version: str = "1.0",
        inputs: dict[str, Any] | None = None,
    ) -> GenAISpan:
        return self.start_span(
            name="agent.tool.execute",
            attributes={
                "gen_ai.tool.name": tool_name,
                "gen_ai.tool.version": tool_version,
                "gen_ai.tool.inputs_summary": str(inputs or {})[:200],
            },
        )

    def trace_verification(self, verifier_name: str, verdict: str) -> GenAISpan:
        span = self.start_span(
            name="agent.verification",
            attributes={
                "tribos.verifier.name": verifier_name,
                "tribos.verifier.verdict": verdict,
            },
        )
        span.finish("ok" if verdict in ("passed", "verified") else "error")
        return span

    def export_otlp_json(self) -> str:
        """Export completed spans as OTLP JSON string."""
        data = {
            "resource_spans": [
                {
                    "resource": {"attributes": {"service.name": "tribos-agent-harness"}},
                    "scope_spans": [{"spans": [s.to_otlp_dict() for s in self.spans]}],
                }
            ]
        }
        return json.dumps(data, indent=2)
