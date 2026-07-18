from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, field_validator


# --- Status & layer enums ---

class VerificationStatus(str, Enum):

    VALID = "valid"
    INVALID = "invalid"
    SUSPICIOUS = "suspicious"
    UNCERTAIN = "uncertain"


class FailedLayer(str, Enum):

    SYNTAX = "syntax"
    DNS = "dns"
    ML = "ml"
    SMTP = "smtp"
    NULL = "null"


# --- Inbound payload ---

class EmailVerifyRequest(BaseModel):

    email: str

    @field_validator("email")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()

    model_config = {
        "json_schema_extra": {
            "example": {"email": "dulanma.weerakotuwa@outlook.com"}
        }
    }


# --- Outbound payload ---

class EmailVerifyResponse(BaseModel):

    email: str
    status: VerificationStatus
    confidence: float
    failed_layer: FailedLayer
    reasons: list[str]
    suggestion: str
    execution_times: dict[str, float] = {}
    ml_score: float = 0.0
    
    # Surfaced for the frontend dashboard — not strictly part of the verdict
    syntax_valid: bool = False
    mx_records: list[str] = []
    is_disposable: bool = False
    smtp_deliverable: Optional[bool] = None
    is_catchall: bool = False
    spf_present: bool = False
    dmarc_present: bool = False
    is_role_address: bool = False

    # Moved out of the ML layer — these are static lookups, not learned signals
    domain_known_provider: bool = False
    domain_tld_suspicious: bool = False

    model_config = {
        "json_schema_extra": {
            "example": {
                "email": "temp123@mailinator.com",
                "status": "suspicious",
                "confidence": 0.82,
                "failed_layer": "ml",
                "reasons": [
                    "Domain 'mailinator.com' is a known disposable provider.",
                    "Local-part 'temp123' contains suspicious token patterns."
                ],
                "suggestion": "Please use a permanent personal or work email address."
            }
        }
    }


# --- Mutable context that travels through the CoR chain ---

class PipelineContext(BaseModel):

    email: str
    local_part: str = ""
    domain: str = ""

    # Each layer enriches or short-circuits these
    status: VerificationStatus = VerificationStatus.VALID
    confidence: float = 1.0
    failed_layer: FailedLayer = FailedLayer.NULL
    reasons: list[str] = []
    suggestion: str = ""

    # Layer-specific signals — downstream handlers read these
    syntax_valid: bool = False
    mx_records: list[str] = []
    ml_score: float = 0.0          # 0 = clean, 1 = garbage
    smtp_reachable: Optional[bool] = None  # None = not yet checked
    is_catchall: bool = False              # True if domain accepts all addresses
    is_disposable: bool = False            # True if ML or cache flags it as disposable
    spf_present: bool = False
    dmarc_present: bool = False
    is_role_address: bool = False

    # Static domain checks — used to be ML features but belong in DNS
    # because they're table lookups, not learned patterns
    domain_known_provider: bool = False
    domain_tld_suspicious: bool = False

    # When True, the chain stops — no further handlers run
    stop_processing: bool = False

    # Per-layer ms timings — used in the dissertation latency tables
    execution_times: dict[str, float] = {}

    class Config:
        arbitrary_types_allowed = True