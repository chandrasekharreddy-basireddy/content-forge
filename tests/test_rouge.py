"""Tests for the ROUGE-L implementation.

This is the function behind the headline number in the report, so it gets
known-answer tests rather than a smoke test. A wrong LCS produces numbers that
look perfectly plausible, which is exactly why it needs pinning.
"""

from rouge import corpus_rouge_l, lcs_length, rouge_l, tokens


def test_tokens_drop_punctuation_and_case():
    assert tokens("The cost fell 14%, in 2025.") == ["the", "cost", "fell", "14%", "in", "2025"]


def test_identical_text_scores_one():
    assert rouge_l("a b c d", "a b c d")["f1"] == 1.0


def test_lcs_counts_a_subsequence_not_a_substring():
    assert lcs_length(["a", "b", "c"], ["a", "c"]) == 2
    assert lcs_length(["a", "b", "c"], ["c", "b", "a"]) == 1
    assert lcs_length([], ["a"]) == 0


def test_precision_and_recall_are_asymmetric():
    """A summary longer than the reference has lower precision, higher recall."""
    scores = rouge_l("a b c d e f", "a b c")
    assert scores["precision"] < scores["recall"]
    assert 0 < scores["f1"] < 1


def test_disjoint_text_scores_zero():
    assert rouge_l("alpha beta", "gamma delta")["f1"] == 0.0


def test_empty_input_scores_zero_rather_than_dividing_by_zero():
    assert rouge_l("", "a b") == {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    assert rouge_l("a b", "") == {"precision": 0.0, "recall": 0.0, "f1": 0.0}


def test_corpus_average_of_no_documents_is_zero():
    assert corpus_rouge_l([])["f1"] == 0.0


def test_corpus_average_is_the_mean_of_the_pairs():
    pairs = [("a b c", "a b c"), ("x y", "p q")]
    corpus = corpus_rouge_l(pairs)
    assert corpus["f1"] == round((1.0 + 0.0) / 2, 4)
