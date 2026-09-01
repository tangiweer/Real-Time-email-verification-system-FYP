

from __future__ import annotations
import re
import time
from app.models import PipelineContext, VerificationStatus, FailedLayer
from app.pipeline.base_handler import BaseEmailHandler

# RFC 5322-ish regex — broad enough for unicode local-parts, strict enough to catch junk
_EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9._%+\-\u00C0-\u024F\u0400-\u04FF]+"   # local-part (incl. unicode letters)
    r"@"
    r"[a-zA-Z0-9\-]+"                                    # domain
    r"(\.[a-zA-Z0-9\-]+)*"                              # subdomains
    r"\.[a-zA-Z]{2,}$",                                  # TLD
    re.UNICODE
)

MAX_EMAIL_LENGTH = 254       # RFC 5321 total email address limit
MAX_LOCAL_LENGTH = 64        # RFC 5321 local-part limit
MAX_DOMAIN_LENGTH = 253      # RFC 5321 domain limit
# SAFETY: bail before the regex even sees anything over 320 chars — avoids catastrophic backtracking
SANITY_MAX_LENGTH = 320


class SyntaxHandler(BaseEmailHandler):


    async def handle(self, context: PipelineContext) -> PipelineContext:
        start_time = time.perf_counter()
        email = context.email.strip()

        # Gate: absurdly long strings can blow up the regex engine
        if len(email) > SANITY_MAX_LENGTH:
            return self._fail(
                context,
                start_time,
                f"Email address is unreasonably long ({len(email)} characters). "
                f"Rejecting to prevent potential regex catastrophe."
            )

        # RFC 5321 caps the full address at 254 chars
        if len(email) > MAX_EMAIL_LENGTH:
            return self._fail(
                context,
                start_time,
                f"Email address exceeds the RFC 5321 maximum length of {MAX_EMAIL_LENGTH} characters."
            )

        # Exactly one '@' — two means something is very wrong
        if email.count("@") != 1:
            return self._fail(
                context,
                start_time,
                "Email address must contain exactly one '@' symbol."
            )

        local_part, domain = email.rsplit("@", 1)

        # Both sides of the '@' need to actually exist and be within spec
        if not local_part:
            return self._fail(context, start_time, "Local-part (before '@') cannot be empty.")

        if len(local_part) > MAX_LOCAL_LENGTH:
            return self._fail(
                context,
                start_time,
                f"Local-part exceeds RFC 5321 maximum of {MAX_LOCAL_LENGTH} characters."
            )

        if not domain or len(domain) > MAX_DOMAIN_LENGTH:
            return self._fail(
                context,
                start_time,
                f"Domain part is missing or exceeds RFC 5321 maximum of {MAX_DOMAIN_LENGTH} characters."
            )

        # Final regex pass for anything the structural checks missed
        if not _EMAIL_REGEX.match(email):
            return self._fail(
                context,
                start_time,
                f"Email address does not conform to RFC 5322 syntax rules."
            )

        # RFC 1123: hyphens can't start or end a label
        if domain.startswith("-") or domain.endswith("-") or ".-" in domain or "-." in domain:
            return self._fail(
                context,
                start_time,
                "Domain labels cannot begin or end with a hyphen (RFC 1123)."
            )

        # Consecutive dots are never valid
        if ".." in local_part or ".." in domain:
            return self._fail(context, start_time, "Email address contains consecutive dots, which is not permitted.")

        # Leading/trailing dots in the local-part are also illegal
        if local_part.startswith(".") or local_part.endswith("."):
            return self._fail(context, start_time, "Local-part cannot start or end with a dot.")

        # All good — stash the parsed parts for downstream handlers
        context.syntax_valid = True
        context.local_part = local_part
        context.domain = domain

        # Record how long syntax took (feeds the latency breakdown tables)
        context.execution_times[self.layer_name] = round((time.perf_counter() - start_time) * 1000, 1)

        # Hand off to the next link in the chain
        return await super().handle(context)

    # Stamp INVALID and kill the chain in one shot

    def _fail(self, context: PipelineContext, start_time: float, reason: str) -> PipelineContext:
        context.execution_times[self.layer_name] = round((time.perf_counter() - start_time) * 1000, 1)
        context.status = VerificationStatus.INVALID
        context.confidence = 0.99
        context.failed_layer = FailedLayer.SYNTAX
        context.reasons.append(reason)
        context.suggestion = (
            "Please check that you have entered a valid email address "
            "(e.g. yourname@example.com)."
        )
        context.stop_processing = True
        return context
