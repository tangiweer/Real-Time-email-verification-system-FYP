

import math
from collections import Counter


def shannon_entropy(text: str) -> float:

    if not text:
        return 0.0

    length = len(text)
    freq = Counter(text.lower())
    entropy = -sum((count / length) * math.log2(count / length)
                   for count in freq.values())
    # Do not round here.  The deployed model was trained with the full-precision
    # value, so rounding changes its input vector.
    return entropy


def normalised_entropy(text: str) -> float:

    if len(text) < 2:
        return 0.0

    # Must match train_model_colab.py: normalise against the maximum entropy
    # possible for the local-part length, not the number of unique characters.
    return shannon_entropy(text) / math.log2(len(text))
