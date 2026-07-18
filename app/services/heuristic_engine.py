

from __future__ import annotations
import re
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.disposable_cache import DisposableDomainsCache

# Domains so obviously legitimate that flagging them is embarrassing
REPUTABLE_DOMAINS: set[str] = {
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "aol.com",
    "protonmail.com", "pm.me", "fastmail.com", "zoho.com", "tutanota.com",
    "mail.com", "yandex.com", "gmx.com", "posteo.de", "riseup.net",
}

# TLD patterns for educational/government institutions — high trust
TRUSTED_TLD_PATTERNS: list[str] = [
    r"\.ac\.[a-z]{2}$",   # .ac.uk, .ac.lk, etc.
    r"\.edu$",
    r"\.edu\.[a-z]{2}$",  # .edu.au, .edu.in, etc.
    r"\.gov$",
    r"\.gov\.[a-z]{2}$",
    r"\.org$",
]

# Known QWERTY keyboard row sequences — runs of 4+ chars from these are mashing
_QWERTY_ROWS = [
    "qwertyuiop",
    "asdfghjkl",
    "zxcvbnm",
]


class HeuristicEngine:


    def __init__(self, disposable_cache: Optional["DisposableDomainsCache"] = None) -> None:
        self._cache = disposable_cache

    def adjust_score(self, email: str, ml_score: float) -> tuple[float, list[str]]:

        if "@" not in email:
            return ml_score, []

        local_part, domain = email.rsplit("@", 1)
        domain_lower = domain.lower()
        local_lower = local_part.lower()
        notes: list[str] = []
        multiplier = 1.0

        # Dynamic check against live blocklist
        is_disposable = False
        if self._cache is not None:
            is_disposable = self._cache.is_disposable(domain_lower)

        if is_disposable:
            notes.append(f"Domain '{domain}' is a known disposable provider (from live blocklist).")
            return min(ml_score * 1.5, 1.0), notes   # amplify, don't reduce

        # Hard override: major providers should never be penalised
        if domain_lower in REPUTABLE_DOMAINS:
            multiplier *= 0.5
            notes.append(f"Domain '{domain}' is a reputable email provider.")

        # Institutional TLDs (.edu, .gov, .ac.*) get a trust bump
        for pattern in TRUSTED_TLD_PATTERNS:
            if re.search(pattern, domain_lower):
                multiplier *= 0.4
                # Looks like a custom domain — trust it more
                notes.append(f"Domain uses a trusted institutional TLD.")
                break

        # Discount for name-like local parts
        if self._looks_like_human_name(local_lower):
            multiplier *= 0.6
            notes.append("Local-part resembles a human name pattern.")

        # Prefixes like "info@", "admin@" — common on corporate domains
        local_root = local_lower.split("+", 1)[0]
        if local_root in {"admin", "support", "info", "noreply", "no-reply", "postmaster", "webmaster", "abuse"}:
            notes.append("Local-part appears to be a role-based address (e.g., admin@, support@).")

        # firstname.lastname convention is a strong human signal
        if re.match(r"^[a-z]+\.[a-z]+$", local_lower):
            multiplier *= 0.55
            notes.append("Email follows a firstname.lastname convention.")

        # Clamp to [0, 1]
        adjusted = round(ml_score * multiplier, 4)
        return adjusted, notes

    @staticmethod
    def _looks_like_human_name(local: str) -> bool:

        if not (2 <= len(local) <= 40):
            return False
        alpha_chars = sum(c.isalpha() for c in local)
        alpha_ratio = alpha_chars / max(len(local), 1)
        digit_runs = re.findall(r"\d+", local)
        # Too many numbers usually = bots or test accounts
        if not (alpha_ratio >= 0.70 and len(digit_runs) <= 1):
            return False

        # Reject keyboard-mash: 5+ consecutive consonants is usually not a natural name
        consonants = set("bcdfghjklmnpqrstvwxyz")
        max_consec = 0
        cur = 0
        for ch in local.lower():
            if ch in consonants:
                cur += 1
                max_consec = max(max_consec, cur)
            else:
                cur = 0
        if max_consec >= 5:
            return False

        # Reject known QWERTY row runs of 4+ consecutive characters
        local_lower = local.lower()
        for row in _QWERTY_ROWS:
            # Walk through every 4+ char substring and check for runs
            for start in range(len(row) - 3):
                for length in range(4, len(row) - start + 1):
                    fragment = row[start:start + length]
                    if fragment in local_lower:
                        return False

        return True
