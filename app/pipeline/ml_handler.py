

from __future__ import annotations
import time
from typing import Optional, TYPE_CHECKING
from app.models import PipelineContext, VerificationStatus, FailedLayer
from app.pipeline.base_handler import BaseEmailHandler
from app.services.ml_model import MLModelService
from app.services.heuristic_engine import HeuristicEngine
from app.services.cache_service import cache_service
from app.core.config import EXTRACTOR_SETTINGS

if TYPE_CHECKING:
    from app.services.disposable_cache import DisposableDomainsCache

import os

PASS_THRESHOLD = float(os.getenv("ML_PASS_THRESHOLD", "0.35"))
SUSPICIOUS_THRESHOLD = float(os.getenv("ML_SUSPICIOUS_THRESHOLD", "0.65"))
ROLE_PREFIXES = EXTRACTOR_SETTINGS["ROLE_PREFIXES"]


class MLHandler(BaseEmailHandler):


    def __init__(
        self,
        disposable_cache: Optional["DisposableDomainsCache"] = None,
    ) -> None:
        super().__init__()
        self._model = MLModelService()
        self._heuristic = HeuristicEngine(disposable_cache=disposable_cache)

    def warmup(self) -> None:

        self._model.predict_email_risk("warmup@gmail.com")
        super().warmup()

    async def handle(self, context: PipelineContext) -> PipelineContext:
        start_time = time.perf_counter()
        email = context.email


        cache_key = f"ml:pred:{email}"
        cached_val = await cache_service.get(cache_key)
        
        if cached_val is not None:
            raw_score, label = cached_val
        else:
            raw_score = self._model.predict_email_risk(email)
            label = "suspicious" if raw_score >= 0.5 else "legitimate"
            # Cache predictions for 24h — same email hitting us twice in a day gets the fast path
            await cache_service.set(cache_key, [raw_score, label], ttl_seconds=86400)
        context.ml_score = raw_score

        try:
            local_root = email.rsplit("@", 1)[0].split("+", 1)[0].lower()
            if local_root in ROLE_PREFIXES:
                context.is_role_address = True
        except Exception:
            pass

        # Flag known disposable domains from the live blocklist
        if self._heuristic._cache and self._heuristic._cache.is_disposable(context.domain.lower()):
            context.is_disposable = True

        # Let the heuristic engine temper the raw score (bias mitigation)
        adjusted_score, heuristic_notes = self._heuristic.adjust_score(email, raw_score)

        # Three-tier decision: clean → pass, middle → warn, high → reject
        if adjusted_score < PASS_THRESHOLD:
            # Below threshold — let it through to SMTP for the final check
            if heuristic_notes:
                context.reasons.extend(heuristic_notes)
            context.execution_times[self.layer_name] = round((time.perf_counter() - start_time) * 1000, 1)
            return await super().handle(context)

        if adjusted_score < SUSPICIOUS_THRESHOLD:
            # Grey area — suspicious enough to flag, not enough to hard-block
            context.status = VerificationStatus.SUSPICIOUS
            context.confidence = round(adjusted_score, 2)
            context.failed_layer = FailedLayer.ML
            context.reasons.append(
                f"Email address pattern suggests it may be temporary or auto-generated "
                f"(suspicion score: {adjusted_score:.0%})."
            )
            if heuristic_notes:
                context.reasons.extend(heuristic_notes)
            context.suggestion = (
                "This address appears suspicious.  If this is a legitimate address, "
                "please proceed — the verification is not definitive."
            )

            context.execution_times[self.layer_name] = round((time.perf_counter() - start_time) * 1000, 1)
            return await super().handle(context)

        # Confidence is high enough to kill the chain here — skip SMTP entirely
        context.status = VerificationStatus.INVALID
        context.confidence = round(adjusted_score, 2)
        context.failed_layer = FailedLayer.ML
        context.is_disposable = True
        context.reasons.append(
            f"Email address is classified as disposable or bot-generated "
            f"(suspicion score: {adjusted_score:.0%})."
        )
        if heuristic_notes:
            context.reasons.extend(heuristic_notes)
        context.suggestion = (
            "Please use a permanent personal or work email address rather than "
            "a temporary or disposable one."
        )
        context.stop_processing = True
        context.execution_times[self.layer_name] = round((time.perf_counter() - start_time) * 1000, 1)
        return context
