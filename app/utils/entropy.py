

import math
from collections import Counter


def shannon_entropy(text: str) -> float:

    if not text:
        return 0.0

    length = len(text)
    freq = Counter(text.lower())
    entropy = -sum((count / length) * math.log2(count / length)
                   for count in freq.values())
    return round(entropy, 4)


def normalised_entropy(text: str) -> float:

    if not text or len(set(text)) <= 1:
        return 0.0

    raw = shannon_entropy(text)
    max_entropy = math.log2(len(set(text.lower())))
    if max_entropy == 0:
        return 0.0
    return round(raw / max_entropy, 4)
