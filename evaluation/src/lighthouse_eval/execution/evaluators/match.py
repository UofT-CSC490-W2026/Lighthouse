from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from lighthouse_eval.candidates.base import Completion, _CandidateBase
from lighthouse_eval.datasets.schema import EvaluatorKind, MatchMetrics, OutputFormat, Task


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


def _resolve_workspace_read_path(workspace: Path, relative_path: str) -> Path:
    path = Path(relative_path)
    if path.is_absolute():
        raise ValueError(f"Match ground_truth paths must be relative: {relative_path!r}")

    workspace_root = workspace.resolve()
    target = (workspace / path).resolve(strict=False)
    try:
        target.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError(f"Match ground_truth path escapes workspace: {relative_path!r}") from exc
    return target


def _serialise_file_map(file_map: Mapping[str, str]) -> str:
    parts: list[str] = []
    for path in sorted(file_map):
        parts.append(f"===== {path} =====")
        parts.append(file_map[path])
    return "\n".join(parts)


def _extract_generated_payload(
    task: Task,
    candidate: _CandidateBase,
    workspace: Path,
) -> tuple[str, str]:
    spec = task.match_spec
    if spec is None:
        raise ValueError(f"Task {task.id} has no match_spec")

    if task.output_format == OutputFormat.completion:
        if not isinstance(candidate, Completion):
            raise TypeError(
                f"Completion match task {task.id} expects Completion candidate, "
                f"got {type(candidate).__name__}"
            )
        return candidate.text, spec.ground_truth["_completion"]

    generated_files: dict[str, str] = {}
    expected_files: dict[str, str] = {}
    for rel_path, expected_content in spec.ground_truth.items():
        target = _resolve_workspace_read_path(workspace, rel_path)
        generated_files[rel_path] = target.read_text(encoding="utf-8") if target.exists() else ""
        expected_files[rel_path] = expected_content

    return _serialise_file_map(generated_files), _serialise_file_map(expected_files)


class ExactMatchEvaluator:
    """Score by exact string equality against ground truth."""

    kind = EvaluatorKind.match

    async def evaluate(
        self, task: Task, candidate: _CandidateBase, workspace: Path
    ) -> MatchMetrics:
        spec = task.match_spec
        if spec is None:
            raise ValueError(f"Task {task.id} has no match_spec")

        generated, expected = _extract_generated_payload(task, candidate, workspace)

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

        generated, expected = _extract_generated_payload(task, candidate, workspace)

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

        generated, expected = _extract_generated_payload(task, candidate, workspace)

        gen_n = _normalise(generated, strip=spec.strip_whitespace, case=spec.case_sensitive)
        exp_n = _normalise(expected, strip=spec.strip_whitespace, case=spec.case_sensitive)

        return MatchMetrics(
            bleu_score=_bleu_score(gen_n, exp_n),
            character_count_generated=len(generated),
            character_count_expected=len(expected),
        )
