from __future__ import annotations
import math
import re
from app.utils.entropy import shannon_entropy, normalised_entropy
from app.core.config import EXTRACTOR_SETTINGS

SUSPICIOUS_TOKENS = EXTRACTOR_SETTINGS["SUSPICIOUS_TOKENS"]

VOWELS: set[str] = set("aeiouAEIOU")
CONSONANTS: set[str] = set("bcdfghjklmnpqrstvwxyzBCDFGHJKLMNPQRSTVWXYZ")

# QWERTY key positions — used to detect keyboard-walk gibberish (e.g. "asdfgh")
# Offsets model the physical stagger between rows on a real keyboard.
QWERTY_COORDS: dict[str, tuple[float, float]] = {
    # Top row (row 0)
    'q': (0, 0),  'w': (0, 1),  'e': (0, 2),  'r': (0, 3),  't': (0, 4),
    'y': (0, 5),  'u': (0, 6),  'i': (0, 7),  'o': (0, 8),  'p': (0, 9),
    # Home row — shifted 0.25 right to match a real QWERTY stagger
    'a': (1, 0.25), 's': (1, 1.25), 'd': (1, 2.25), 'f': (1, 3.25), 'g': (1, 4.25),
    'h': (1, 5.25), 'j': (1, 6.25), 'k': (1, 7.25), 'l': (1, 8.25),
    # Bottom row — shifted 0.75 right
    'z': (2, 0.75), 'x': (2, 1.75), 'c': (2, 2.75), 'v': (2, 3.75), 'b': (2, 4.75),
    'n': (2, 5.75), 'm': (2, 6.75),
    # Number row sits above the letters
    '1': (-1, 0), '2': (-1, 1), '3': (-1, 2), '4': (-1, 3), '5': (-1, 4),
    '6': (-1, 5), '7': (-1, 6), '8': (-1, 7), '9': (-1, 8), '0': (-1, 9),
}

CONSONANT_CHARS_LOWER: set[str] = set("bcdfghjklmnpqrstvwxyz")

# Column order must match what the trained RF model expects
FEATURE_ORDER: list[str] = [
    "local_length", "domain_length", "digit_ratio",
    "special_char_ratio", "vowel_ratio", "consonant_ratio",
    "entropy", "normalised_entropy", "has_repeated_chars",
    "suspicious_token", "digit_run_length", "dot_count",
    "hyphen_count", "starts_with_digit",
    "max_consecutive_consonants", "avg_qwerty_distance",
    "domain_hyphen_count", "domain_digit_ratio",
]


class FeatureExtractor:


    def extract(self, email: str) -> dict[str, float]:

        if "@" not in email:
            return self._zero_features()

        local_part, domain = email.rsplit("@", 1)
        return self._compute_features(local_part, domain)

    def extract_as_vector(self, email: str) -> list[float]:

        d = self.extract(email)
        return [d[k] for k in FEATURE_ORDER]

    # --- Private helpers ---

    def _compute_features(self, local: str, domain: str) -> dict[str, float]:
        local_lower = local.lower()
        domain_lower = domain.lower()
        length = len(local_lower) or 1  # avoid division by zero

        # How many chars are digits?
        digits = [c for c in local_lower if c.isdigit()]
        digit_ratio = len(digits) / length

        # Unusual punctuation (not ., -, _) is a mild red flag
        specials = [c for c in local_lower if not c.isalnum() and c not in (".", "-", "_")]
        special_ratio = len(specials) / length

        # Vowel/consonant balance helps distinguish real names from random mashing
        vowels = [c for c in local_lower if c in VOWELS]
        consonants = [c for c in local_lower if c in CONSONANTS]
        vowel_ratio = len(vowels) / length
        consonant_ratio = len(consonants) / length

        # Shannon entropy — high = random, low = repetitive
        entropy = shannon_entropy(local_lower)
        norm_entropy = normalised_entropy(local_lower)

        # Runs like "aaa" or "111" are a strong bot signal
        has_repeated = 1.0 if re.search(r"(.)\1{2,}", local_lower) else 0.0

        # Check for words like "temp", "trash", "mailinator" in either part
        combined = local_lower + " " + domain_lower
        has_suspicious_token = float(
            any(tok in combined for tok in SUSPICIOUS_TOKENS)
        )

        # Long unbroken digit sequences (e.g. "1234567890") are suspicious
        digit_runs = re.findall(r"\d+", local_lower)
        digit_run_length = max((len(r) for r in digit_runs), default=0)

        # Dots and hyphens in the local-part
        dot_count = local_lower.count(".")
        hyphen_count = local_lower.count("-")
        starts_with_digit = 1.0 if local_lower and local_lower[0].isdigit() else 0.0

        # --- Keyboard-derived features ---

        # Long consonant clusters ("xkstrm") scream random generation
        max_consec_consonants = float(self._max_consecutive_consonants(local_lower))

        # Low distance = adjacent keys being mashed; high = deliberate typing
        avg_qwerty_dist = self._avg_qwerty_distance(local_lower)

        # Domain-level signals — shady TLDs and hyphen-heavy domains
        domain_hyphen_count = float(domain_lower.count("-"))
        domain_digits = sum(1 for c in domain_lower if c.isdigit())
        domain_digit_ratio = domain_digits / len(domain_lower) if domain_lower else 0.0

        return {
            "local_length": float(len(local)),
            "domain_length": float(len(domain)),
            "digit_ratio": digit_ratio,
            "special_char_ratio": special_ratio,
            "vowel_ratio": vowel_ratio,
            "consonant_ratio": consonant_ratio,
            "entropy": entropy,
            "normalised_entropy": norm_entropy,
            "has_repeated_chars": has_repeated,
            "suspicious_token": has_suspicious_token,
            "digit_run_length": float(digit_run_length),
            "dot_count": float(dot_count),
            "hyphen_count": float(hyphen_count),
            "starts_with_digit": starts_with_digit,
            "max_consecutive_consonants": max_consec_consonants,
            "avg_qwerty_distance": avg_qwerty_dist,
            "domain_hyphen_count": domain_hyphen_count,
            "domain_digit_ratio": float(domain_digit_ratio),
        }

    # --- QWERTY spatial distance ---

    @staticmethod
    def _qwerty_distance(c1: str, c2: str) -> float:

        pos1 = QWERTY_COORDS.get(c1.lower())
        pos2 = QWERTY_COORDS.get(c2.lower())
        if pos1 is None or pos2 is None:
            return 0.0
        return math.sqrt((pos1[0] - pos2[0]) ** 2 + (pos1[1] - pos2[1]) ** 2)

    @staticmethod
    def _avg_qwerty_distance(text: str) -> float:

        # Only score characters we have coords for
        mappable = [c for c in text.lower() if c in QWERTY_COORDS]
        if len(mappable) < 2:
            return 0.0

        total_distance = sum(
            FeatureExtractor._qwerty_distance(mappable[i], mappable[i + 1])
            for i in range(len(mappable) - 1)
        )
        return round(total_distance / (len(mappable) - 1), 4)

    # --- Consecutive consonant clusters ---

    @staticmethod
    def _max_consecutive_consonants(text: str) -> int:

        max_run = 0
        current_run = 0
        for c in text.lower():
            if c in CONSONANT_CHARS_LOWER:
                current_run += 1
                max_run = max(max_run, current_run)
            else:
                current_run = 0
        return max_run

    @staticmethod
    def _feature_order() -> list[str]:

        return FEATURE_ORDER

    @staticmethod
    def _zero_features() -> dict[str, float]:

        return {k: 0.0 for k in FEATURE_ORDER}
