"""ROUGE-L, written out in full.

Why hand-write it instead of pip installing rouge-score? Because there are
about forty lines of it, it removes a dependency from the evaluation, and if
an examiner asks what ROUGE-L measures you can point at the function.

ROUGE-L compares a generated summary with a reference summary using the
longest common subsequence (LCS) of their words. It rewards keeping the
reference's words in the reference's order, without requiring them to be
adjacent. Precision and recall come from the LCS length; F1 combines them.
"""

import re

WORD = re.compile(r"[a-z0-9%]+")


def tokens(text: str) -> list[str]:
    """Lowercase word tokens. Punctuation is not evidence, so it is dropped."""
    return WORD.findall((text or "").lower())


def lcs_length(a: list[str], b: list[str]) -> int:
    """Length of the longest common subsequence of two token lists.

    Classic dynamic programming, one row at a time. Keeping only two rows
    means memory is O(len(b)) rather than O(len(a) * len(b)).
    """
    if not a or not b:
        return 0

    previous = [0] * (len(b) + 1)
    for token_a in a:
        current = [0] * (len(b) + 1)
        for index, token_b in enumerate(b, start=1):
            if token_a == token_b:
                current[index] = previous[index - 1] + 1
            else:
                current[index] = max(previous[index], current[index - 1])
        previous = current
    return previous[-1]


def rouge_l(generated: str, reference: str, beta: float = 1.2) -> dict:
    """Return precision, recall and F1 for one generated/reference pair.

    beta=1.2 weights recall slightly above precision, which is the ROUGE
    convention: missing something important is worse than adding a little.
    """
    gen = tokens(generated)
    ref = tokens(reference)

    if not gen or not ref:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    lcs = lcs_length(gen, ref)
    precision = lcs / len(gen)
    recall = lcs / len(ref)

    if precision + recall == 0:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    beta_squared = beta**2
    f1 = (1 + beta_squared) * precision * recall / (recall + beta_squared * precision)

    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def corpus_rouge_l(pairs: list[tuple[str, str]]) -> dict:
    """Average ROUGE-L across many documents, as a paper would report it."""
    if not pairs:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    scores = [rouge_l(generated, reference) for generated, reference in pairs]
    count = len(scores)
    return {
        key: round(sum(score[key] for score in scores) / count, 4)
        for key in ("precision", "recall", "f1")
    }
