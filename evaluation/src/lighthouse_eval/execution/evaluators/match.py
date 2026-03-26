from __future__ import annotations

from pathlib import Path

from lighthouse_eval.candidates.base import Completion, _CandidateBase
from lighthouse_eval.datasets.schema import EvaluatorKind, MatchMetrics, Task


def _normalise(text: str, *, strip: bool, case: bool) -> str:
    if strip:
        text = text.strip()
    if not case:
        text = text.lower()
    return text


def _edit_distance(a: str, b: str) -> int:
    """Standard Levenshtein distance (character-level)."""
    if len(a) < len(b):
        return _edit_distance(b, a)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


def _edit_similarity(a: str, b: str) -> float:
    max_len = max(len(a), len(b))
    if max_len == 0:
        return 1.0
    return 1.0 - _edit_distance(a, b) / max_len


def _bleu_score(hypothesis: str, reference: str) -> float:
    """Sentence-level BLEU-4 with simple tokenisation."""
    from collections import Counter

    def _ngrams(tokens: list[str], n: int) -> Counter:
        return Counter(tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1))

    hyp_tokens = hypothesis.split()
    ref_tokens = reference.split()
    if not hyp_tokens:
        return 0.0

    import math

    score = 0.0
    for n in range(1, 5):
        hyp_ng = _ngrams(hyp_tokens, n)
        ref_ng = _ngrams(ref_tokens, n)
        clipped = sum(min(hyp_ng[ng], ref_ng[ng]) for ng in hyp_ng)
        total = max(sum(hyp_ng.values()), 1)
        precision = clipped / total
        if precision == 0:
            return 0.0
        score += math.log(precision)
    score /= 4.0

    brevity = min(1.0, len(hyp_tokens) / max(len(ref_tokens), 1))
    if brevity < 1.0:
        score += 1.0 - 1.0 / brevity

    return math.exp(score)


def _extract_generated_text(candidate: _CandidateBase) -> str:
    if isinstance(candidate, Completion):
        return candidate.text
    raise TypeError(f"MatchEvaluator expects Completion candidate, got {type(candidate).__name__}")


class ExactMatchEvaluator:
    """Score by exact string equality against ground truth."""

    kind = EvaluatorKind.match

    async def evaluate(
        self, task: Task, candidate: _CandidateBase, workspace: Path
    ) -> MatchMetrics:
        spec = task.match_spec
        if spec is None:
            raise ValueError(f"Task {task.id} has no match_spec")

        generated = _extract_generated_text(candidate)
        expected = spec.ground_truth.get("_completion", "")

        gen_n = _normalise(generated, strip=spec.strip_whitespace, case=spec.case_sensitive)
        exp_n = _normalise(expected, strip=spec.strip_whitespace, case=spec.case_sensitive)

        return MatchMetrics(
            exact_match=(gen_n == exp_n),
            character_count_generated=len(generated),
            character_count_expected=len(expected),
        )


class EditSimilarityEvaluator:
    """Score by normalised edit distance."""

    kind = EvaluatorKind.match

    async def evaluate(
        self, task: Task, candidate: _CandidateBase, workspace: Path
    ) -> MatchMetrics:
        spec = task.match_spec
        if spec is None:
            raise ValueError(f"Task {task.id} has no match_spec")

        generated = _extract_generated_text(candidate)
        expected = spec.ground_truth.get("_completion", "")

        gen_n = _normalise(generated, strip=spec.strip_whitespace, case=spec.case_sensitive)
        exp_n = _normalise(expected, strip=spec.strip_whitespace, case=spec.case_sensitive)

        return MatchMetrics(
            edit_similarity=_edit_similarity(gen_n, exp_n),
            character_count_generated=len(generated),
            character_count_expected=len(expected),
        )


class BLEUEvaluator:
    """Score by sentence-level BLEU-4."""

    kind = EvaluatorKind.match

    async def evaluate(
        self, task: Task, candidate: _CandidateBase, workspace: Path
    ) -> MatchMetrics:
        spec = task.match_spec
        if spec is None:
            raise ValueError(f"Task {task.id} has no match_spec")

        generated = _extract_generated_text(candidate)
        expected = spec.ground_truth.get("_completion", "")

        gen_n = _normalise(generated, strip=spec.strip_whitespace, case=spec.case_sensitive)
        exp_n = _normalise(expected, strip=spec.strip_whitespace, case=spec.case_sensitive)

        return MatchMetrics(
            bleu_score=_bleu_score(gen_n, exp_n),
            character_count_generated=len(generated),
            character_count_expected=len(expected),
        )
