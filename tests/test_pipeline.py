

from __future__ import annotations
import pytest
import asyncio
from unittest.mock import patch, MagicMock

from app.models import PipelineContext, VerificationStatus, FailedLayer
from app.pipeline.syntax_handler import SyntaxHandler
from app.pipeline.dns_handler import DNSHandler
from app.pipeline.ml_handler import MLHandler
from app.pipeline.smtp_handler import SMTPHandler
from app.services.feature_extractor import FeatureExtractor
from app.services.heuristic_engine import HeuristicEngine
from app.utils.entropy import shannon_entropy, normalised_entropy


#  Helpers 

from app.services.cache_service import cache_service

@pytest.fixture(autouse=True)
def clear_caches():
    SMTPHandler._CATCHALL_CACHE.clear()
    if hasattr(cache_service, "_in_memory_cache"):
        cache_service._in_memory_cache.clear()

def make_context(email: str) -> PipelineContext:
    return PipelineContext(email=email)


async def run_syntax(email: str) -> PipelineContext:
    handler = SyntaxHandler()
    return await handler.handle(make_context(email))


async def run_dns(email: str, mx_side_effect=None) -> PipelineContext:
    handler = DNSHandler()
    ctx = make_context(email)
    ctx.syntax_valid = True
    local, domain = email.rsplit("@", 1)
    ctx.local_part = local
    ctx.domain = domain
    if mx_side_effect:
        with patch.object(DNSHandler, '_lookup_mx', side_effect=mx_side_effect):
            return await handler.handle(ctx)
    return await handler.handle(ctx)


# 1. Utility tests

class TestEntropy:
    def test_zero_entropy_uniform_string(self):
        assert shannon_entropy("aaaaaa") == 0.0

    def test_nonzero_entropy_mixed_string(self):
        assert shannon_entropy("abc123!") > 0.0

    def test_empty_string(self):
        assert shannon_entropy("") == 0.0

    def test_normalised_entropy_range(self):
        for text in ["hello", "xkz92p", "firstname.lastname", "aaa"]:
            val = normalised_entropy(text)
            assert 0.0 <= val <= 1.0, f"Out of range for '{text}': {val}"

    def test_high_entropy_random_string(self):
        assert shannon_entropy("xk7z2pQ9") > 2.5


# 2. Feature Extractor tests

class TestFeatureExtractor:
    extractor = FeatureExtractor()

    def test_vector_length(self):

        vec = self.extractor.extract_as_vector("john.doe@gmail.com")
        assert len(vec) == 18

    def test_suspicious_token_detected(self):
        features = self.extractor.extract("temp123@mailinator.com")
        assert features["suspicious_token"] == 1.0

    def test_no_suspicious_token_for_legit(self):
        features = self.extractor.extract("john.smith@gmail.com")
        assert features["suspicious_token"] == 0.0

    def test_digit_ratio_correct(self):
        features = self.extractor.extract("abc123@example.com")
        # local-part = "abc123" → 3 digits out of 6 chars
        assert abs(features["digit_ratio"] - 0.5) < 0.01

    def test_repeated_chars_flag(self):
        features = self.extractor.extract("aaa111@example.com")
        assert features["has_repeated_chars"] == 1.0

    def test_no_repeated_chars_normal(self):
        features = self.extractor.extract("alice@example.com")
        assert features["has_repeated_chars"] == 0.0

    def test_starts_with_digit(self):
        features = self.extractor.extract("123user@example.com")
        assert features["starts_with_digit"] == 1.0

    #  Enhancement B: Consecutive consonant clusters 

    def test_consecutive_consonants_high_for_bot_string(self):

        features = self.extractor.extract("xkstrm@example.com")
        assert features["max_consecutive_consonants"] >= 6

    def test_consecutive_consonants_moderate_for_slavic_name(self):

        features = self.extractor.extract("krzysztof@example.com")
        # 'krzysztof' → 'k-r-z-y-s-z-t' = 7 consecutive consonants before 'o'
        # This is expected for Slavic names — the ML model learns to tolerate
        # this when combined with other legitimate-name signals.
        assert features["max_consecutive_consonants"] >= 5

    def test_consecutive_consonants_low_for_natural_name(self):

        features = self.extractor.extract("john@example.com")
        assert features["max_consecutive_consonants"] <= 3

    #  Enhancement B: QWERTY spatial distance ─

    def test_qwerty_distance_low_for_keyboard_walk(self):

        features = self.extractor.extract("asdfgh@example.com")
        assert features["avg_qwerty_distance"] < 2.0

    def test_qwerty_distance_higher_for_natural_name(self):

        feat_natural = self.extractor.extract("john@example.com")
        feat_keyboard = self.extractor.extract("asdf@example.com")
        assert feat_natural["avg_qwerty_distance"] > feat_keyboard["avg_qwerty_distance"]

    def test_qwerty_distance_present_in_features(self):

        features = self.extractor.extract("user@example.com")
        assert "avg_qwerty_distance" in features
        assert "max_consecutive_consonants" in features


# 3. Heuristic Engine tests

class TestHeuristicEngine:
    engine = HeuristicEngine()

    def test_reputable_domain_reduces_score(self):
        original = 0.6
        adjusted, _ = self.engine.adjust_score("user@gmail.com", original)
        assert adjusted < original

    def test_disposable_domain_amplifies_score(self):
        original = 0.5
        adjusted, _ = self.engine.adjust_score("x@mailinator.com", original)
        assert adjusted >= original

    def test_firstname_lastname_reduces_score(self):
        original = 0.55
        adjusted, _ = self.engine.adjust_score("john.smith@gmail.com", original)
        assert adjusted < original

    def test_diverse_name_high_entropy_not_amplified(self):
        # Culturally diverse name — should not be amplified
        original = 0.45
        adjusted, _ = self.engine.adjust_score("thiruvenkadam.r@icloud.com", original)
        assert adjusted <= original

    def test_academic_tld_reduces_score(self):
        original = 0.5
        adjusted, notes = self.engine.adjust_score("student@university.ac.uk", original)
        assert adjusted < original
        assert any("institutional" in n for n in notes)


# 4. Syntax Layer tests

class TestSyntaxHandler:

    @pytest.mark.asyncio
    async def test_valid_simple(self):
        ctx = await run_syntax("user@example.com")
        assert ctx.syntax_valid is True
        assert ctx.status == VerificationStatus.VALID

    @pytest.mark.asyncio
    async def test_valid_with_dots_and_plus(self):
        ctx = await run_syntax("user.name+tag@sub.example.co.uk")
        assert ctx.syntax_valid is True

    @pytest.mark.asyncio
    async def test_missing_at_symbol(self):
        ctx = await run_syntax("invalidemail.com")
        assert ctx.status == VerificationStatus.INVALID
        assert ctx.failed_layer == FailedLayer.SYNTAX

    @pytest.mark.asyncio
    async def test_double_at(self):
        ctx = await run_syntax("user@@example.com")
        assert ctx.status == VerificationStatus.INVALID

    @pytest.mark.asyncio
    async def test_missing_domain(self):
        ctx = await run_syntax("user@")
        assert ctx.status == VerificationStatus.INVALID

    @pytest.mark.asyncio
    async def test_missing_local(self):
        ctx = await run_syntax("@example.com")
        assert ctx.status == VerificationStatus.INVALID

    @pytest.mark.asyncio
    async def test_consecutive_dots(self):
        ctx = await run_syntax("user..name@example.com")
        assert ctx.status == VerificationStatus.INVALID

    @pytest.mark.asyncio
    async def test_local_starts_with_dot(self):
        ctx = await run_syntax(".user@example.com")
        assert ctx.status == VerificationStatus.INVALID

    @pytest.mark.asyncio
    async def test_email_too_long(self):
        long_email = "a" * 250 + "@example.com"
        ctx = await run_syntax(long_email)
        assert ctx.status == VerificationStatus.INVALID

    @pytest.mark.asyncio
    async def test_international_domain(self):
        ctx = await run_syntax("user@münchen.de")
        # May pass or fail depending on regex — should not throw exception
        assert ctx.status in (VerificationStatus.VALID, VerificationStatus.INVALID)

    @pytest.mark.asyncio
    async def test_local_part_and_domain_extracted(self):
        ctx = await run_syntax("hello@world.org")
        assert ctx.local_part == "hello"
        assert ctx.domain == "world.org"

    @pytest.mark.asyncio
    async def test_stop_flag_set_on_failure(self):
        ctx = await run_syntax("notanemail")
        assert ctx.stop_processing is True


# 5. DNS Layer tests (mocked to avoid real network calls)

class TestDNSHandler:

    @pytest.mark.asyncio
    async def test_valid_mx_passes(self):
        with patch.object(DNSHandler, '_lookup_mx', return_value=(["mail.example.com"], False, False, None)):
            ctx = await run_dns("user@example.com")
        assert ctx.mx_records == ["mail.example.com"]
        assert ctx.status == VerificationStatus.VALID

    @pytest.mark.asyncio
    async def test_nxdomain_rejected(self):
        with patch.object(DNSHandler, '_lookup_mx', return_value=([], False, False, "nxdomain")):
            ctx = await run_dns("user@nonexistent999.com")
        assert ctx.status == VerificationStatus.INVALID
        assert ctx.failed_layer == FailedLayer.DNS

    @pytest.mark.asyncio
    async def test_no_mx_record_rejected(self):
        with patch.object(DNSHandler, '_lookup_mx', return_value=([], False, False, "no_mx")):
            ctx = await run_dns("user@nomx.example.com")
        assert ctx.status == VerificationStatus.INVALID
        assert ctx.failed_layer == FailedLayer.DNS

    @pytest.mark.asyncio
    async def test_timeout_returns_uncertain(self):
        with patch.object(DNSHandler, '_lookup_mx', return_value=([], False, False, "timeout")):
            ctx = await run_dns("user@slow.example.com")
        assert ctx.status == VerificationStatus.UNCERTAIN
        assert ctx.failed_layer == FailedLayer.DNS

    @pytest.mark.asyncio
    async def test_dns_error_returns_uncertain(self):
        with patch.object(DNSHandler, '_lookup_mx', return_value=([], False, False, "dns_error")):
            ctx = await run_dns("user@broken.example.com")
        assert ctx.status == VerificationStatus.UNCERTAIN


# 6. ML Layer tests

class TestMLHandler:

    def _make_ml_ctx(self, email: str) -> PipelineContext:
        ctx = make_context(email)
        ctx.syntax_valid = True
        ctx.mx_records = ["mail.example.com"]
        ctx.local_part, ctx.domain = email.rsplit("@", 1)
        return ctx

    @pytest.mark.asyncio
    async def test_disposable_email_flagged(self):
        handler = MLHandler()
        ctx = self._make_ml_ctx("temp123@mailinator.com")
        ctx = await handler.handle(ctx)
        assert ctx.status in (VerificationStatus.SUSPICIOUS, VerificationStatus.INVALID)
        assert ctx.failed_layer == FailedLayer.ML

    @pytest.mark.asyncio
    async def test_legitimate_gmail_passes_or_uncertain(self):
        handler = MLHandler()
        ctx = self._make_ml_ctx("john.smith@gmail.com")
        ctx = await handler.handle(ctx)
        # Should not be hard-rejected as invalid by ML
        assert ctx.status != VerificationStatus.INVALID or ctx.failed_layer != FailedLayer.ML

    @pytest.mark.asyncio
    async def test_culturally_diverse_name_not_hard_rejected(self):

        handler = MLHandler()
        diverse_emails = [
            "thiruvenkadam.r@gmail.com",
            "krzysztof.nowak@outlook.com",
            "dulanma.weerakotuwa@icloud.com",
            "abdulrahman.hassan@protonmail.com",
            "nguyen.thi.lan@gmail.com",
        ]
        for email in diverse_emails:
            ctx = self._make_ml_ctx(email)
            result = await handler.handle(ctx)
            assert result.status != VerificationStatus.INVALID, (
                f"Culturally diverse name falsely rejected: {email}"
            )

    @pytest.mark.asyncio
    async def test_high_entropy_alone_not_invalid(self):

        handler = MLHandler()
        # Slavic-style high-entropy but legitimate-looking name on reputable domain
        ctx = self._make_ml_ctx("zbigniew.szczepanski@gmail.com")
        result = await handler.handle(ctx)
        assert result.status != VerificationStatus.INVALID


# 7. SMTP Layer tests (mocked)

class TestSMTPHandler:

    def _make_smtp_ctx(self, email: str, mx: list = None) -> PipelineContext:
        ctx = make_context(email)
        ctx.syntax_valid = True
        ctx.mx_records = mx or ["mail.example.com"]
        ctx.local_part, ctx.domain = email.rsplit("@", 1)
        return ctx

    @pytest.mark.asyncio
    async def test_smtp_reachable_marks_valid(self):
        handler = SMTPHandler()
        with patch.object(SMTPHandler, '_is_catchall_domain', return_value=False), \
             patch.object(SMTPHandler, '_probe_smtp', return_value=("reachable", "250 OK")):
            ctx = await handler.handle(self._make_smtp_ctx("user@example.com"))
        assert ctx.smtp_reachable is True
        assert ctx.status == VerificationStatus.VALID

    @pytest.mark.asyncio
    async def test_smtp_rejected_marks_invalid(self):
        handler = SMTPHandler()
        with patch.object(SMTPHandler, '_is_catchall_domain', return_value=False), \
             patch.object(SMTPHandler, '_probe_smtp', return_value=("rejected", "550 No such user")):
            ctx = await handler.handle(self._make_smtp_ctx("ghost@example.com"))
        assert ctx.status == VerificationStatus.INVALID
        assert ctx.failed_layer == FailedLayer.SMTP

    @pytest.mark.asyncio
    async def test_smtp_timeout_returns_uncertain(self):
        handler = SMTPHandler()
        with patch.object(SMTPHandler, '_is_catchall_domain', return_value="not_catchall"), \
             patch.object(SMTPHandler, '_probe_smtp', return_value=("timeout", "")):
            ctx = await handler.handle(self._make_smtp_ctx("user@slow.com"))
        assert ctx.status == VerificationStatus.UNCERTAIN

    @pytest.mark.asyncio
    async def test_blocked_port_returns_uncertain(self):
        handler = SMTPHandler()
        with patch.object(SMTPHandler, '_is_catchall_domain', return_value="not_catchall"), \
             patch.object(SMTPHandler, '_probe_smtp', return_value=("blocked_port", "Connection refused")):
            ctx = await handler.handle(self._make_smtp_ctx("user@example.com"))
        assert ctx.status == VerificationStatus.UNCERTAIN

    @pytest.mark.asyncio
    async def test_no_mx_records_returns_uncertain(self):
        handler = SMTPHandler()
        ctx = self._make_smtp_ctx("user@example.com", mx=[])
        result = await handler.handle(ctx)
        assert result.status == VerificationStatus.UNCERTAIN

    #  Enhancement A: Catch-all pre-probe tests ─

    @pytest.mark.asyncio
    async def test_catchall_preprobe_skips_smtp_verdict(self):

        handler = SMTPHandler()
        ctx = self._make_smtp_ctx("user@catchall-corp.com")
        with patch.object(SMTPHandler, '_is_catchall_domain', return_value="catchall"):
            result = await handler.handle(ctx)
        assert result.is_catchall is True
        assert result.status == VerificationStatus.UNCERTAIN
        assert any("catch-all" in r.lower() for r in result.reasons)

    @pytest.mark.asyncio
    async def test_non_catchall_proceeds_normally(self):

        handler = SMTPHandler()
        ctx = self._make_smtp_ctx("user@normal-corp.com")
        with patch.object(SMTPHandler, '_is_catchall_domain', return_value="not_catchall"), \
             patch.object(SMTPHandler, '_probe_smtp', return_value=("reachable", "250 OK")):
            result = await handler.handle(ctx)
        assert result.is_catchall is False
        assert result.smtp_reachable is True
        assert result.status == VerificationStatus.VALID

    @pytest.mark.asyncio
    async def test_catchall_flag_set_on_context(self):

        handler = SMTPHandler()
        ctx = self._make_smtp_ctx("anyone@catchall.example.com")
        with patch.object(SMTPHandler, '_is_catchall_domain', return_value=True):
            result = await handler.handle(ctx)
        assert result.is_catchall is True

    @pytest.mark.asyncio
    async def test_catchall_preserves_prior_suspicious_status(self):

        handler = SMTPHandler()
        ctx = self._make_smtp_ctx("shady@catchall-corp.com")
        ctx.status = VerificationStatus.SUSPICIOUS
        ctx.confidence = 0.55
        ctx.failed_layer = FailedLayer.ML
        with patch.object(SMTPHandler, '_is_catchall_domain', return_value=True):
            result = await handler.handle(ctx)
        assert result.is_catchall is True
        # Should preserve the ML suspicious status, not downgrade to uncertain
        assert result.status == VerificationStatus.SUSPICIOUS


# 8. Disposable Domain Cache tests (Enhancement C)

class TestDisposableCache:

    def test_cache_seed_data(self, tmp_path):

        from app.services.disposable_cache import DisposableDomainsCache
        db_path = str(tmp_path / "test_disposable.db")
        cache = DisposableDomainsCache(db_path=db_path)
        assert cache.domain_count > 0

    def test_cache_lookup_known_disposable(self, tmp_path):

        from app.services.disposable_cache import DisposableDomainsCache
        db_path = str(tmp_path / "test_disposable.db")
        cache = DisposableDomainsCache(db_path=db_path)
        assert cache.is_disposable("mailinator.com") is True
        assert cache.is_disposable("guerrillamail.com") is True

    def test_cache_lookup_non_disposable(self, tmp_path):

        from app.services.disposable_cache import DisposableDomainsCache
        db_path = str(tmp_path / "test_disposable.db")
        cache = DisposableDomainsCache(db_path=db_path)
        assert cache.is_disposable("gmail.com") is False
        assert cache.is_disposable("outlook.com") is False

    def test_cache_case_insensitive(self, tmp_path):

        from app.services.disposable_cache import DisposableDomainsCache
        db_path = str(tmp_path / "test_disposable.db")
        cache = DisposableDomainsCache(db_path=db_path)
        assert cache.is_disposable("MAILINATOR.COM") is True
        assert cache.is_disposable("Mailinator.Com") is True

    def test_heuristic_engine_uses_cache(self, tmp_path):

        from app.services.disposable_cache import DisposableDomainsCache
        db_path = str(tmp_path / "test_disposable.db")
        cache = DisposableDomainsCache(db_path=db_path)
        engine = HeuristicEngine(disposable_cache=cache)
        original = 0.5
        adjusted, notes = engine.adjust_score("x@mailinator.com", original)
        assert adjusted >= original
        assert any("disposable" in n.lower() for n in notes)


# 9. Full Pipeline Integration Tests

def build_full_pipeline():
    from app.pipeline.syntax_handler import SyntaxHandler
    from app.pipeline.dns_handler import DNSHandler
    from app.pipeline.ml_handler import MLHandler
    from app.pipeline.smtp_handler import SMTPHandler
    s = SyntaxHandler(); d = DNSHandler(); m = MLHandler(); p = SMTPHandler()
    s.set_next(d).set_next(m).set_next(p)
    return s


class TestFullPipeline:

    @pytest.mark.asyncio
    async def test_invalid_syntax_stops_early(self):
        pipeline = build_full_pipeline()
        ctx = await pipeline.handle(make_context("notanemail"))
        assert ctx.status == VerificationStatus.INVALID
        assert ctx.failed_layer == FailedLayer.SYNTAX
        assert ctx.stop_processing is True

    @pytest.mark.asyncio
    async def test_valid_email_reaches_smtp(self):
        pipeline = build_full_pipeline()
        with patch.object(DNSHandler, '_lookup_mx', return_value=(["mail.gmail.com"], False, False, None)), \
             patch.object(SMTPHandler, '_is_catchall_domain', return_value=False), \
             patch.object(SMTPHandler, '_probe_smtp', return_value=("reachable", "250 OK")):
            ctx = await pipeline.handle(make_context("john.smith@gmail.com"))
        assert ctx.status == VerificationStatus.VALID
        assert ctx.failed_layer == FailedLayer.NULL

    @pytest.mark.asyncio
    async def test_disposable_stopped_at_ml(self):
        pipeline = build_full_pipeline()
        with patch.object(DNSHandler, '_lookup_mx', return_value=(["mail.mailinator.com"], False, False, None)):
            ctx = await pipeline.handle(make_context("temp999@mailinator.com"))
        assert ctx.status in (VerificationStatus.SUSPICIOUS, VerificationStatus.INVALID)
        assert ctx.failed_layer == FailedLayer.ML

    @pytest.mark.asyncio
    async def test_smtp_timeout_gives_uncertain_not_invalid(self):
        pipeline = build_full_pipeline()
        with patch.object(DNSHandler, '_lookup_mx', return_value=(["mail.example.com"], False, False, None)), \
             patch.object(SMTPHandler, '_is_catchall_domain', return_value=False), \
             patch.object(SMTPHandler, '_probe_smtp', return_value=("timeout", "")):
            ctx = await pipeline.handle(make_context("real.user@example.com"))
        # Should be uncertain, not invalid — timeout is not proof of non-existence
        assert ctx.status == VerificationStatus.UNCERTAIN

    @pytest.mark.asyncio
    async def test_nxdomain_stops_at_dns(self):
        pipeline = build_full_pipeline()
        with patch.object(DNSHandler, '_lookup_mx', return_value=([], False, False, "nxdomain")):
            ctx = await pipeline.handle(make_context("user@totallyfakedomain99999.xyz"))
        assert ctx.status == VerificationStatus.INVALID
        assert ctx.failed_layer == FailedLayer.DNS

    @pytest.mark.asyncio
    async def test_reasons_list_populated(self):
        pipeline = build_full_pipeline()
        ctx = await pipeline.handle(make_context("bad-email"))
        assert len(ctx.reasons) > 0

    @pytest.mark.asyncio
    async def test_suggestion_populated_on_failure(self):
        pipeline = build_full_pipeline()
        ctx = await pipeline.handle(make_context("@@bad"))
        assert ctx.suggestion != ""

    @pytest.mark.asyncio
    async def test_catchall_domain_returns_uncertain_in_pipeline(self):

        pipeline = build_full_pipeline()
        with patch.object(DNSHandler, '_lookup_mx', return_value=(["mail.catchall.com"], False, False, None)), \
             patch.object(SMTPHandler, '_is_catchall_domain', return_value=True):
            ctx = await pipeline.handle(make_context("user@catchall.com"))
        assert ctx.is_catchall is True
        assert ctx.status == VerificationStatus.UNCERTAIN


def test_application_pipeline_order_matches_documented_flow():

    from app.main import _build_pipeline

    pipeline = _build_pipeline()
    assert isinstance(pipeline, SyntaxHandler)
    assert isinstance(pipeline._next_handler, DNSHandler)
    assert isinstance(pipeline._next_handler._next_handler, MLHandler)
    assert isinstance(pipeline._next_handler._next_handler._next_handler, SMTPHandler)
