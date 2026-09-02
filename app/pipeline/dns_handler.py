from __future__ import annotations
import asyncio
import time
from typing import Optional
import dns.resolver
import dns.exception
import dns.asyncresolver
from app.models import PipelineContext, VerificationStatus, FailedLayer
from app.pipeline.base_handler import BaseEmailHandler
from app.services.cache_service import cache_service

DNS_TIMEOUT = 5.0       # seconds before treating lookup as inconclusive
DNS_LIFETIME = 8.0      # maximum total time for all retries


class DNSHandler(BaseEmailHandler):


    async def handle(self, context: PipelineContext) -> PipelineContext:
        start_time = time.perf_counter()
        domain = context.domain

        if not domain:
            return self._fail(context, start_time, "Domain could not be extracted from the email address.")

        # Hit the cache first — DNS results are stable enough to survive a day
        cache_key = f"dns:{domain}"
        cached_val = await cache_service.get(cache_key)
        
        if cached_val is not None:
            mx_records, spf_present, dmarc_present, error = cached_val
        else:
            # Cache miss — go to the wire and also grab SPF/DMARC while we're at it
            mx_records, spf_present, dmarc_present, error = await self._lookup_mx(domain)
            # Stash the result; MX records don't change often (24h TTL)
            await cache_service.set(cache_key, [mx_records, spf_present, dmarc_present, error], ttl_seconds=86400)

        if error == "nxdomain":
            return self._fail(
                context,
                start_time,
                f"The domain '{domain}' does not exist (NXDOMAIN)."
            )

        if error == "no_mx":
            return self._fail(
                context,
                start_time,
                f"The domain '{domain}' has no MX records — it cannot receive email."
            )

        if error == "timeout":
            # Timeout ≠ invalid. The server might just be slow; don't punish the user.
            context.execution_times[self.layer_name] = round((time.perf_counter() - start_time) * 1000, 1)
            context.status = VerificationStatus.UNCERTAIN
            context.confidence = 0.45
            context.failed_layer = FailedLayer.DNS
            context.reasons.append(
                f"DNS lookup for '{domain}' timed out.  Cannot confirm mail server."
            )
            context.suggestion = "The domain may exist but its DNS server is slow.  Please try again shortly."
            context.stop_processing = True
            return context

        if error == "dns_error":
            context.execution_times[self.layer_name] = round((time.perf_counter() - start_time) * 1000, 1)
            context.status = VerificationStatus.UNCERTAIN
            context.confidence = 0.40
            context.failed_layer = FailedLayer.DNS
            context.reasons.append(
                f"A DNS resolution error occurred for '{domain}'.  Verification is inconclusive."
            )
            context.suggestion = "DNS resolution failed.  Please verify the domain is spelled correctly."
            context.stop_processing = True
            return context

        # DNS looks good — attach records and move on
        context.mx_records = mx_records
        context.spf_present = bool(spf_present)
        context.dmarc_present = bool(dmarc_present)
        context.execution_times[self.layer_name] = round((time.perf_counter() - start_time) * 1000, 1)
        return await super().handle(context)

    # Async MX resolution (+ piggybacked SPF/DMARC TXT lookups)

    @staticmethod
    async def _lookup_mx(domain: str) -> tuple[list[str], bool, bool, Optional[str]]:

        resolver = dns.asyncresolver.Resolver()
        resolver.timeout = DNS_TIMEOUT
        resolver.lifetime = DNS_LIFETIME

        try:
            answers = await resolver.resolve(domain, "MX")
            # RFC 5321 requires trying the lowest numeric preference first.
            # Alphabetical sorting can select a backup MX as the primary server.
            mx_with_priority = [
                (r.preference, str(r.exchange).rstrip(".")) for r in answers
                if str(r.exchange) != "."  # RFC 7505 null-MX: domain accepts no mail
            ]
            mx_list = [host for _, host in sorted(mx_with_priority, key=lambda item: item[0])]
            if not mx_list:
                return [], False, False, "no_mx"

            # While we have the resolver open, peek at TXT for SPF and DMARC
            spf_present = False
            dmarc_present = False
            try:
                txt_answers = await resolver.resolve(domain, "TXT")
                for r in txt_answers:
                    txt = b"".join(r.strings).decode(errors="ignore") if hasattr(r, "strings") else str(r)
                    if "v=spf1" in txt.lower():
                        spf_present = True
                        break
            except Exception:
                pass

            try:
                dname = f"_dmarc.{domain}"
                dtxt = await resolver.resolve(dname, "TXT")
                for r in dtxt:
                    txt = b"".join(r.strings).decode(errors="ignore") if hasattr(r, "strings") else str(r)
                    if "v=dmarc1" in txt.lower():
                        dmarc_present = True
                        break
            except Exception:
                pass

            return mx_list, spf_present, dmarc_present, None

        except dns.resolver.NXDOMAIN:
            return [], False, False, "nxdomain"

        except dns.resolver.NoAnswer:
            # Domain exists but published no MX — some tiny hosts use A-record fallback
            # Check for A record fallback (some small domains deliver via A record)
            try:
                await resolver.resolve(domain, "A")
                # A record exists but no MX — technically can still receive mail, but unlikely
                return [], False, False, "no_mx"
            except Exception:
                return [], False, False, "no_mx"

        except dns.exception.Timeout:
            return [], False, False, "timeout"

        except dns.resolver.NoNameservers:
            return [], False, False, "dns_error"

        except Exception:
            return [], False, False, "dns_error"

    # Shorthand for a hard DNS rejection

    def _fail(self, context: PipelineContext, start_time: float, reason: str) -> PipelineContext:
        context.execution_times[self.layer_name] = round((time.perf_counter() - start_time) * 1000, 1)
        context.status = VerificationStatus.INVALID
        context.confidence = 0.95
        context.failed_layer = FailedLayer.DNS
        context.reasons.append(reason)
        context.suggestion = (
            "Please ensure the domain part of your email address is correct "
            "and belongs to an active mail provider."
        )
        context.stop_processing = True
        return context
