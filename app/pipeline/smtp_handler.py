from __future__ import annotations
import asyncio
import random
import string
import aiosmtplib
import time
import os
from app.models import PipelineContext, VerificationStatus, FailedLayer
from app.pipeline.base_handler import BaseEmailHandler
from app.services.cache_service import cache_service

SMTP_TIMEOUT = 3           # seconds (reduced to fail fast if port is blocked)
SMTP_PORT = int(os.getenv("SMTP_PORT", 25))
PROBE_FROM = os.getenv("SMTP_FROM_ADDRESS" )   # innocuous sender used in HELO
EHLO_HOSTNAME = os.getenv("SMTP_EHLO_HOST")
# Hard ceiling per-host — anything beyond this is almost certainly blocked or broken
SMTP_CONNECT_TIMEOUT = 6.0   # seconds per MX host attempt
SMTP_TOTAL_TIMEOUT = 15.0    # total seconds for the entire SMTP layer,
                             # INCLUDING time spent waiting for a semaphore slot


class SMTPHandler(BaseEmailHandler):
    # HACK: kept as a class dict so legacy tests that poke at it don't break
    _CATCHALL_CACHE: dict = {}

    def __init__(self) -> None:
        super().__init__()
        self._semaphore = asyncio.Semaphore(10)

    async def handle(self, context: PipelineContext) -> PipelineContext:
        start_time = time.perf_counter()
        if not context.mx_records:
            context.reasons.append(
                "SMTP probe skipped: no MX records available from DNS layer."
            )
            return await self._uncertain(context, start_time, "No MX records to probe.")

        mx_host = context.mx_records[0]   # Highest-priority MX server
        domain = context.domain

        # Acquire semaphore within the total timeout limit to bound tail latency
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=SMTP_TOTAL_TIMEOUT)
        except asyncio.TimeoutError:
            context.execution_times[self.layer_name] = round((time.perf_counter() - start_time) * 1000, 1)
            context.status = VerificationStatus.UNCERTAIN
            context.confidence = 0.5
            context.reasons.append(
                "SMTP layer is under heavy load — verification deferred to protect service latency."
            )
            context.stop_processing = True
            return context

        try:
            remaining = max(0.5, SMTP_TOTAL_TIMEOUT - (time.perf_counter() - start_time))
            return await asyncio.wait_for(
                self._run_smtp_layer(context, mx_host, domain, start_time),
                timeout=remaining,
            )
        except asyncio.TimeoutError:
            context.execution_times[self.layer_name] = round((time.perf_counter() - start_time) * 1000, 1)
            context.status = VerificationStatus.UNCERTAIN
            context.confidence = 0.5
            context.reasons.append(
                f"SMTP verification did not complete within {SMTP_TOTAL_TIMEOUT}s."
            )
            context.stop_processing = True
            return context
        finally:
            self._semaphore.release()

    async def _run_smtp_layer(self, context: PipelineContext, mx_host: str, domain: str, start_time: float) -> PipelineContext:
        """Execute SMTP verification for a single MX host."""
        # Run the canary probe first — if it's a catch-all, there's no point probing the real address
        catchall_status = await self._is_catchall_domain(mx_host, domain)

        if catchall_status == "greylisted":
            context.smtp_reachable = None
            context.reasons.append(
                f"Canary probe to '{mx_host}' was greylisted. Real probe skipped to save latency."
            )
            return await self._uncertain(context, start_time, "greylisted")

        if catchall_status == "blocked":
            context.smtp_reachable = None
            context.reasons.append(
                f"Port {SMTP_PORT} is blocked or timed out when contacting '{mx_host}'. SMTP probe aborted."
            )
            return await self._uncertain(context, start_time, "blocked")

        if catchall_status in ("catchall", True):
            context.is_catchall = True
            context.smtp_reachable = None
            context.reasons.append(
                f"Domain '{domain}' is a catch-all server — SMTP verification is unreliable.  Relying on DNS and ML layer verdicts only."
            )
            if context.status == VerificationStatus.VALID:
                context.status = VerificationStatus.UNCERTAIN
                context.confidence = max(context.confidence * 0.7, 0.50)
                context.failed_layer = FailedLayer.SMTP
                context.suggestion = (
                    "This domain accepts all email addresses (catch-all policy).  "
                    "SMTP verification cannot confirm whether this specific mailbox exists.  Consider sending a confirmation email."
                )
            context.execution_times[self.layer_name] = round((time.perf_counter() - start_time) * 1000, 1)
            return context

        # Jitter between 100-800ms to avoid looking like an automated scanner
        jitter_delay = random.uniform(0.1, 0.8)
        await asyncio.sleep(jitter_delay)

        cache_key = f"smtp_probe:{context.email}"
        cached_probe = await cache_service.get(cache_key)

        if cached_probe:
            result, detail = cached_probe["result"], cached_probe["detail"]
        else:
            result, detail = await self._probe_smtp(mx_host, context.email)
            if result in ("rejected", "reachable"):
                await cache_service.set(cache_key, {"result": result, "detail": detail}, ttl_seconds=43200)

        if result == "reachable":
            context.smtp_reachable = True
            if context.status == VerificationStatus.VALID:
                context.confidence = 0.92
                context.reasons.append(f"SMTP server '{mx_host}' accepted the EHLO handshake.")
            context.execution_times[self.layer_name] = round((time.perf_counter() - start_time) * 1000, 1)
            return context

        if result == "rejected":
            if context.status != VerificationStatus.INVALID:
                context.status = VerificationStatus.INVALID
                context.confidence = 0.88
                context.failed_layer = FailedLayer.SMTP
                context.reasons.append(f"SMTP server '{mx_host}' rejected the recipient address: {detail}")
                context.suggestion = (
                    "The mail server indicated this address does not exist.  Please double-check the address."
                )
            context.smtp_reachable = False
            context.execution_times[self.layer_name] = round((time.perf_counter() - start_time) * 1000, 1)
            return context

        # Nothing definitive — map the result string to a human-readable reason
        context.smtp_reachable = None
        reason_map = {
            "timeout": f"SMTP connection to '{mx_host}' timed out.",
            "blocked_port": f"Port {SMTP_PORT} is blocked — SMTP probe not possible.",
            "greylisted": f"Mail server '{mx_host}' returned a temporary deferral (greylisting).",
            "error": f"An error occurred during SMTP probe of '{mx_host}': {detail}",
        }
        context.reasons.append(reason_map.get(result, f"SMTP probe inconclusive for '{mx_host}'."))
        return await self._uncertain(context, start_time, result)

    @staticmethod
    async def _is_catchall_domain(mx_host: str, domain: str) -> str:

        # Check Redis first so we don't re-probe domains we already know about
        cache_key = f"catchall:{domain}"
        cached_status = await cache_service.get(cache_key)
        if cached_status:
            return cached_status

        # HACK: when port 25 is blocked (dev / CI), skip the network call entirely
        if os.getenv("MOCK_SMTP") == "1":
            return "not_catchall"

        # Build a canary address that no sane mailbox would match
        random_local = (
            ''.join(random.choices(string.ascii_lowercase + string.digits, k=16))
            + '_probe_'
            + str(random.randint(10000, 99999))
        )
        canary_email = f"{random_local}@{domain}"

        smtp = aiosmtplib.SMTP(hostname=mx_host, port=SMTP_PORT, timeout=SMTP_TIMEOUT)
        status = "error"
        try:
            await asyncio.wait_for(smtp.connect(), timeout=SMTP_CONNECT_TIMEOUT)
            await asyncio.wait_for(smtp.ehlo(hostname=EHLO_HOSTNAME), timeout=SMTP_CONNECT_TIMEOUT)
            code, msg = await asyncio.wait_for(smtp.mail(PROBE_FROM), timeout=SMTP_CONNECT_TIMEOUT)
            if code != 250:
                try:
                    await asyncio.wait_for(smtp.quit(), timeout=2.0)
                except Exception:
                    pass
                return "error"

            code, _ = await asyncio.wait_for(smtp.rcpt(canary_email), timeout=SMTP_CONNECT_TIMEOUT)

            try:
                await asyncio.wait_for(smtp.quit(), timeout=2.0)
            except Exception:
                pass

            if code == 250:
                status = "catchall"
            elif code in (421, 450, 451, 452):
                status = "greylisted"
            else:
                status = "not_catchall"
        except (aiosmtplib.SMTPConnectError, ConnectionRefusedError, asyncio.TimeoutError, OSError):
            return "blocked"
        except Exception:
            pass  # eat the error — we'll return the default "error" status

        # Only cache deterministic outcomes — transient errors should be retried
        if status != "error":  # Don't cache hard errors so we can retry later
            await cache_service.set(cache_key, status, ttl_seconds=3600)

        return status

    # The actual EHLO → MAIL FROM → RCPT TO handshake

    @staticmethod
    async def _probe_smtp(mx_host: str, email: str) -> tuple[str, str]:
        
        # HACK: mock path for local dev / CI where outbound port 25 is firewalled
        if os.getenv("MOCK_SMTP") == "1":
            # Fake a small delay so benchmarks aren't unrealistically fast
            await asyncio.sleep(0.5)
            return "reachable", "250 2.1.5 Ok (Mocked Response)"

        smtp = aiosmtplib.SMTP(hostname=mx_host, port=SMTP_PORT)
        async def _quiet_quit():
            try:
                await asyncio.wait_for(smtp.quit(), timeout=2.0)
            except Exception:
                pass
        try:
            # Open the connection
            await asyncio.wait_for(smtp.connect(), timeout=SMTP_CONNECT_TIMEOUT)
            # Identify ourselves
            await asyncio.wait_for(smtp.ehlo(hostname=EHLO_HOSTNAME), timeout=SMTP_CONNECT_TIMEOUT)
            # Announce who we claim to be sending from
            code, msg = await asyncio.wait_for(smtp.mail(PROBE_FROM), timeout=SMTP_CONNECT_TIMEOUT)
            if code != 250:
                await _quiet_quit()
                return "error", f"Server rejected MAIL FROM: {msg.decode() if isinstance(msg, bytes) else str(msg)}"
            # The money question: does this recipient exist?
            code, message = await asyncio.wait_for(smtp.rcpt(email), timeout=SMTP_CONNECT_TIMEOUT)
            await _quiet_quit()
            # Parse the response
            msg_str = message.decode('utf-8', errors='replace') if isinstance(message, bytes) else str(message)
            # Map SMTP codes to our internal result taxonomy
            if code == 250:
                return "reachable", msg_str
            if code in (550, 551, 552, 553, 554):
                return "rejected", msg_str
            if code in (421, 450, 451, 452):
                return "greylisted", msg_str
            return "error", f"Unexpected SMTP code {code}: {msg_str}"
        except asyncio.TimeoutError:
            return "timeout", "Connection timed out."
        except aiosmtplib.SMTPConnectError as e:
            return "blocked_port", str(e)
        except aiosmtplib.SMTPServerDisconnected:
            return "error", "Server disconnected unexpectedly."
        except ConnectionRefusedError:
            return "blocked_port", f"Connection refused on port {SMTP_PORT}."
        except OSError as e:
            if "blocked" in str(e).lower() or "unreachable" in str(e).lower():
                return "blocked_port", str(e)
            return "error", str(e)

        except Exception as e:
            return "error", str(e)

    # Fallback for any inconclusive SMTP outcome

    async def _uncertain(self, context: PipelineContext, start_time: float, reason: str) -> PipelineContext:

        context.execution_times[self.layer_name] = round((time.perf_counter() - start_time) * 1000, 1)
        if context.status == VerificationStatus.VALID:
            context.status = VerificationStatus.UNCERTAIN
            context.confidence = max(context.confidence * 0.7, 0.45)
            context.failed_layer = FailedLayer.SMTP
            context.suggestion = (
                "Email verification is inconclusive at the SMTP level.  "
                "The address may be valid — consider sending a confirmation email."
            )
        return await super().handle(context)