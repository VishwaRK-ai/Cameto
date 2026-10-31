import re
from typing import Any, Dict, List, Optional
try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal

from pydantic import BaseModel, Field, field_validator


class IncomingClaim(BaseModel):
    claim_text: str = Field(
        ...,
        min_length=1,
        description="The viral text or claim to be verified."
    )
    deepfake_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Probability (0-100) that the attached image/media is synthetic or AI-generated."
    )
    platform: str = Field(
        ...,
        description="Origin platform of the claim (e.g., 'Reddit', 'Twitter/X', 'WhatsApp')."
    )

    @field_validator("claim_text")
    @classmethod
    def validate_claim_not_whitespace(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("claim_text cannot be empty or contain only whitespace.")
        return trimmed


class AtomicClaim(BaseModel):
    sub_claim: str = Field(
        ...,
        description="Atomic, verifiable sub-statement extracted from the viral post."
    )
    verdict: Literal["True", "False", "Misleading", "Unverified"] = Field(
        ...,
        description="Factual verdict for this sub-claim."
    )
    highlight_color: Literal["green", "red", "amber", "gray"] = Field(
        ...,
        description="Color code: green (True), red (False), amber (Misleading), gray (Unverified)."
    )
    evidence_id: Optional[str] = Field(
        default="E0",
        description="Evidence ID referencing ground truth facts (e.g. E1, E2)."
    )
    exact_quote: Optional[str] = Field(
        default="",
        description="Exact quote extracted directly from retrieved ground truth source."
    )
    quote_verified: bool = Field(
        default=False,
        description="Anti-hallucination verification flag indicating if quote strictly exists in source text."
    )


class AuditResult(BaseModel):
    verdict: Literal["True", "False", "Misleading", "Unverified"] = Field(
        ...,
        description="Final evaluation verdict."
    )
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Engine confidence score between 0 and 100."
    )
    explanation: str = Field(
        ...,
        description="Concise summary explanation rendered in the detected input language."
    )
    counter_message: Optional[str] = Field(
        default="",
        description="Concise 60-word counter-message debunking/clarifying the claim in detected language."
    )
    matched_sources: List[str] = Field(
        default_factory=list,
        description="List of matched sources, document titles, or URLs from verified facts."
    )
    sibling_domains: List[str] = Field(
        default_factory=list,
        description="Certificate Brand Lookalikes discovered in Certificate Transparency logs."
    )
    atomic_claims: List[AtomicClaim] = Field(
        default_factory=list,
        description="Atomic decomposition of the claim with granular veracity highlights."
    )
    agent_trace: List[str] = Field(
        default_factory=list,
        description="Chronological ReAct execution log tracking live tools and reasoning steps."
    )
    detected_language: Optional[str] = Field(
        default="English",
        description="Detected language of input claim (e.g., English, Hindi, Hinglish, etc.)."
    )
    red_team_argument: Optional[str] = Field(
        default=None,
        description="Skeptical debunker / prosecutor argument from multi-agent debate."
    )
    blue_team_argument: Optional[str] = Field(
        default=None,
        description="Generous advocate / defender argument from multi-agent debate."
    )
    manipulation_tactics: List[str] = Field(
        default_factory=list,
        description="Psychological / rhetorical manipulation tactics detected in the claim."
    )
    prebunk_lesson: Optional[str] = Field(
        default="",
        description="Educational inoculation / prebunking explanation of how this psychological scam mechanism works."
    )
    radar_count: int = Field(
        default=1,
        description="Live Crowd Radar footprint: number of semantically similar claims checked across the network in the last 24 hours."
    )
    receipt_id: Optional[str] = Field(
        default="",
        description="Unique receipt identifier for the cryptographic Ed25519 transparency log."
    )
    receipt_signature: Optional[str] = Field(
        default="",
        description="Ed25519 cryptographic signature of the verdict hash and source citations."
    )
    receipt_url: Optional[str] = Field(
        default="",
        description="Direct verification URL for the Ed25519 cryptographic receipt."
    )
    action_dossier: Optional[str] = Field(
        default="",
        description="Official Cybercrime Pre-Fill Report formatted for cybercrime.gov.in / 1930 / Sanchar Saathi."
    )


class ReceiptPayload(BaseModel):
    receipt_id: str
    claim_hash: str
    evidence_hashes: Dict[str, str] = Field(
        default_factory=dict,
        description="SHA-256 hash of each individual ground-truth evidence snippet (E1, E2, ...)."
    )
    atomic_claims: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Exact atomic sub-claims evaluated by the tribunal."
    )
    model_id: str
    verdict: str
    confidence_score: float
    timestamp: str


class VerificationResponse(BaseModel):
    receipt_id: str
    is_valid: bool
    verification_status: str
    algorithm: str
    public_key: str
    signature: str
    receipt: Dict[str, Any]

