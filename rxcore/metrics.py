"""Evaluation metrics: edit distance, CER, WER, precision/recall, Wilson interval."""
import math
import re
import unicodedata


def levenshtein(a, b):
    """Minimum number of insertions, deletions and substitutions turning
    sequence a into sequence b (works on strings and on lists of words)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def similarity(a, b):
    """Normalised Levenshtein similarity in [0, 1]."""
    if not a and not b:
        return 1.0
    return 1.0 - levenshtein(a, b) / float(max(len(a), len(b)))


def normalise_text(text):
    text = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"\s+", " ", text).strip()


def cer(reference, hypothesis):
    """Character error rate = edit distance / reference length. Can exceed 1."""
    ref, hyp = normalise_text(reference), normalise_text(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return levenshtein(ref, hyp) / float(len(ref))


def wer(reference, hypothesis):
    ref, hyp = normalise_text(reference).split(), normalise_text(hypothesis).split()
    if not ref:
        return 0.0 if not hyp else 1.0
    return levenshtein(ref, hyp) / float(len(ref))


def prf(tp, fp, fn, beta=1.0):
    precision = tp / float(tp + fp) if tp + fp else 0.0
    recall = tp / float(tp + fn) if tp + fn else 0.0
    b2 = beta * beta
    denom = b2 * precision + recall
    f = (1 + b2) * precision * recall / denom if denom else 0.0
    return precision, recall, f


def wilson_interval(successes, n, z=1.96):
    """95% confidence interval for a proportion (Wilson score)."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / float(n)
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))
