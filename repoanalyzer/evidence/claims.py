from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from repoanalyzer.core.models import SupportProfile

SUPPORTED_CLAIM_TYPES = {
    "definition_exists",
    "calls",
    "reaches",
    "includes",
    "build_active",
    "build_config",
    "allocation_profile",
    "callback_registers",
    "stores_callback",
    "invokes_callback",
    "callback_dataflow",
    "task_entry_dataflow",
    "scheduler_semantic",
    "task_state_transition",
    "kernel_object_semantic",
    "hook_assert_trace_semantic",
    "heap_allocator_semantic",
    "port_boundary",
    "execution_context",
    "target_profile",
    "file_active",
    "usb_descriptor_semantic",
    "tinyusb_callback_semantic",
    "tinyusb_driver_dispatch_semantic",
    "tinyusb_device_runtime_semantic",
    "tinyusb_host_runtime_semantic",
    "tinyusb_class_protocol_semantic",
    "tinyusb_typec_pd_semantic",
}


@dataclass(frozen=True)
class Claim:
    claim_type: str
    subject: str | None = None
    object: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Claim":
        claim_type = str(data.get("claim_type") or data.get("type") or "").strip()
        if claim_type not in SUPPORTED_CLAIM_TYPES:
            raise ValueError(f"Unsupported claim_type: {claim_type!r}")
        payload = dict(data.get("payload") or {})
        for key, value in data.items():
            if key not in {"claim_type", "type", "subject", "object", "payload"}:
                payload[key] = value
        return cls(
            claim_type=claim_type,
            subject=data.get("subject"),
            object=data.get("object"),
            payload=payload,
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {k: v for k, v in data.items() if v not in (None, [], {})}


@dataclass(frozen=True)
class ExtractedClaim:
    claim: Claim
    text: str
    span_start: int
    span_end: int
    pattern_id: str
    confidence: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim.to_dict(),
            "text": self.text,
            "span": [self.span_start, self.span_end],
            "pattern_id": self.pattern_id,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ClaimExtractionBundle:
    text: str
    extracted_claims: list[ExtractedClaim]
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "claim_extraction.v1",
            "text": self.text,
            "claims": [item.claim.to_dict() for item in self.extracted_claims],
            "extracted_claims": [item.to_dict() for item in self.extracted_claims],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ClaimVerdict:
    claim: Claim
    verdict: str
    reason_code: str
    message: str
    supporting_facts: list[Any] = field(default_factory=list)
    contradicting_facts: list[Any] = field(default_factory=list)
    unknowns: list[Any] = field(default_factory=list)
    response_constraints: list[str] = field(default_factory=list)
    support_level: str = "unknown"
    unknown_reasons: list[str] = field(default_factory=list)
    quality_profile: SupportProfile | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "schema_version": "claim_verdict.v1",
            "claim": self.claim.to_dict(),
            "verdict": self.verdict,
            "reason_code": self.reason_code,
            "message": self.message,
            "supporting_facts": [fact.to_dict() if hasattr(fact, "to_dict") else fact for fact in self.supporting_facts],
            "contradicting_facts": [fact.to_dict() if hasattr(fact, "to_dict") else fact for fact in self.contradicting_facts],
            "unknowns": [unknown.to_dict() if hasattr(unknown, "to_dict") else unknown for unknown in self.unknowns],
            "response_constraints": list(self.response_constraints),
            "support_level": self.support_level,
            "unknown_reasons": list(self.unknown_reasons),
            "quality_profile": self.quality_profile.to_dict() if self.quality_profile else None,
        }
        return {k: v for k, v in data.items() if v not in (None, [], {})}


@dataclass(frozen=True)
class ClaimEvidenceBundle:
    verdicts: list[ClaimVerdict]
    extracted_claims: list[ExtractedClaim] = field(default_factory=list)
    extraction_warnings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def support_level(self) -> str:
        levels = [verdict.support_level for verdict in self.verdicts if verdict.support_level]
        if not levels:
            return "unknown"
        order = {"strong": 0, "medium": 1, "weak": 2, "unknown": 3}
        return max(levels, key=lambda item: order.get(item, 3))

    @property
    def unknown_reasons(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for verdict in self.verdicts:
            for reason in verdict.unknown_reasons:
                if reason not in seen:
                    seen.add(reason)
                    out.append(reason)
        return out

    @property
    def overall_verdict(self) -> str:
        verdicts = [verdict.verdict for verdict in self.verdicts]
        if not verdicts:
            return "unknown"
        if "contradicted" in verdicts:
            return "contradicted"
        if "unknown" in verdicts:
            return "unknown"
        if "conditional" in verdicts:
            return "conditional"
        if all(v == "supported" for v in verdicts):
            return "supported"
        return "unknown"

    def to_dict(self) -> dict[str, Any]:
        data = {
            "schema_version": "claim_evidence_bundle.v1",
            "overall_verdict": self.overall_verdict,
            "support_level": self.support_level,
            "unknown_reasons": self.unknown_reasons,
            "verdicts": [verdict.to_dict() for verdict in self.verdicts],
        }
        if self.extracted_claims:
            data["extracted_claims"] = [item.to_dict() for item in self.extracted_claims]
        if self.extraction_warnings:
            data["extraction_warnings"] = list(self.extraction_warnings)
        return data
