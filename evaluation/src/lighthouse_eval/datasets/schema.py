from __future__ import annotations

import enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class EvaluatorKind(str, enum.Enum):
    """Which evaluation track a task belongs to."""

    test_execution = "test_execution"
    match = "match"
    retrieval_diagnostic = "retrieval_diagnostic"


class OutputFormat(str, enum.Enum):
    """How the LLM's output is structured."""

    file = "file"
    multi_file = "multi_file"
    patch = "patch"
    completion = "completion"


class TestSpec(BaseModel):
    """Spec for tasks evaluated by running a test suite."""

    execution_backend: Literal["local_pytest", "docker_pytest", "command_sequence"] | None = (
        None
    )
    test_paths: list[Path] = Field(default_factory=list)
    test_commands: list[str] = Field(default_factory=list)
    expected_to_pass: list[str] = Field(
        default_factory=list,
        description="Tests that should transition from failing to passing (SWE-bench FAIL_TO_PASS).",
    )
    expected_to_stay_passing: list[str] = Field(
        default_factory=list,
        description="Tests that must remain passing (SWE-bench PASS_TO_PASS).",
    )
    docker_image: str | None = None
    timeout_seconds: int = 300

    @model_validator(mode="after")
    def _validate_execution_backend(self) -> TestSpec:
        if self.execution_backend is None:
            if self.docker_image:
                self.execution_backend = "docker_pytest"
            elif self.test_commands:
                self.execution_backend = "command_sequence"
            elif self.test_paths:
                self.execution_backend = "local_pytest"

        if self.execution_backend is None:
            raise ValueError(
                "TestSpec must declare a runnable backend via execution_backend, "
                "test_commands, or test_paths."
            )

        if self.execution_backend == "docker_pytest":
            if not self.docker_image:
                raise ValueError("docker_pytest requires docker_image to be set.")
            if not (self.test_commands or self.test_paths):
                raise ValueError("docker_pytest requires test_commands or test_paths.")
        elif self.execution_backend == "command_sequence":
            if not self.test_commands:
                raise ValueError("command_sequence requires at least one test command.")
        elif self.execution_backend == "local_pytest":
            if not (self.test_commands or self.test_paths):
                raise ValueError("local_pytest requires test_commands or test_paths.")

        return self


class MatchSpec(BaseModel):
    """Spec for tasks evaluated by comparing output to ground truth."""

    ground_truth: dict[str, str] = Field(
        description=(
            'Map of filename to expected content.  For completion tasks use '
            'the key "_completion" with the expected string.'
        ),
    )
    metric: Literal["exact_match", "edit_similarity", "bleu"] = "exact_match"
    case_sensitive: bool = True
    strip_whitespace: bool = True


class ContextSnippetRef(BaseModel):
    """Lightweight reference to a ground-truth context snippet."""

    snippet_id: str | None = None
    file_path: str
    content: str
    start_line: int | None = None
    end_line: int | None = None


class RetrievalSpec(BaseModel):
    """Spec for tasks that measure retrieval quality directly."""

    ground_truth_snippets: list[ContextSnippetRef] = Field(default_factory=list)
    gold_indices: list[int] = Field(
        default_factory=list,
        description="Indices into the oracle context list that are considered 'correct'.",
    )
    metric: Literal["precision_at_k", "recall_at_k", "mrr"] = "precision_at_k"
    k: int = 10


class TaskProvenance(BaseModel):
    """Tracks exactly where a task came from and how it was transformed."""

    source_dataset: str = Field(
        description='Origin benchmark, e.g. "swebench_lite", "crosscodeeval", "custom:mutations_v1".',
    )
    source_instance_id: str = Field(
        description="Original ID in the source dataset.",
    )
    transform_version: str = Field(
        description="Adapter version that produced this Task. Bump when adapter logic changes.",
    )
    comparability_class: str = Field(
        description=(
            "Groups tasks whose scores can legitimately be compared, "
            'e.g. "swebench:test_execution", "crosscodeeval:exact_match".'
        ),
    )


class Task(BaseModel):
    """Canonical representation of a single evaluation task."""

    id: str = Field(description="Framework-global unique ID.")
    provenance: TaskProvenance

    evaluator_kind: EvaluatorKind
    output_format: OutputFormat

    description: str = Field(description="The coding-task prompt shown to the LLM.")
    language: Literal["python"] = "python"

    workspace_path: Path | None = Field(
        default=None,
        description="Directory with source files.  None when generated on-the-fly.",
    )
    target_files: list[str] = Field(
        default_factory=list,
        description="Relative paths the LLM should generate or modify.",
    )

    test_spec: TestSpec | None = None
    match_spec: MatchSpec | None = None
    retrieval_spec: RetrievalSpec | None = None

    oracle_context: list[ContextSnippetRef] = Field(
        default_factory=list,
        description="Ground-truth context snippets (for StaticProvider / oracle comparison).",
    )

    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_match_spec_compatibility(self) -> Task:
        if self.evaluator_kind != EvaluatorKind.match or self.match_spec is None:
            return self

        ground_truth_keys = list(self.match_spec.ground_truth)
        if self.output_format == OutputFormat.completion:
            if ground_truth_keys != ["_completion"]:
                raise ValueError(
                    "Completion match tasks must provide exactly one ground_truth entry: "
                    "'_completion'."
                )
            return self

        if not ground_truth_keys or "_completion" in self.match_spec.ground_truth:
            raise ValueError(
                "Non-completion match tasks must provide file-keyed ground_truth entries."
            )

        if self.output_format == OutputFormat.file and len(ground_truth_keys) != 1:
            raise ValueError("File match tasks must provide exactly one ground_truth file.")

        return self


class Dataset(BaseModel):
    """An ordered collection of tasks from a single source."""

    name: str
    tasks: list[Task]
    metadata: dict[str, Any] = Field(default_factory=dict)


class TestExecutionMetrics(BaseModel):
    """Metrics from running a test suite."""

    passed: int = 0
    failed: int = 0
    errors: int = 0
    total: int = 0
    pass_rate: float = Field(
        default=0.0,
        description="passed / total  (0.0 when total == 0).",
    )
    fail_to_pass_resolved: int | None = Field(
        default=None,
        description="How many FAIL_TO_PASS tests now pass (SWE-bench specific).",
    )
    pass_to_pass_preserved: int | None = Field(
        default=None,
        description="How many PASS_TO_PASS tests still pass (SWE-bench specific).",
    )


class MatchMetrics(BaseModel):
    """Metrics from comparing generated output to ground truth."""

    exact_match: bool | None = None
    edit_similarity: float | None = Field(
        default=None,
        description="1.0 - (edit_distance / max_len).  1.0 = identical.",
    )
    bleu_score: float | None = None
    character_count_generated: int = 0
    character_count_expected: int = 0


class RetrievalMetrics(BaseModel):
    """Metrics from evaluating retrieval quality."""

    precision_at_k: float | None = None
    recall_at_k: float | None = None
    mrr: float | None = None
    k: int = 10
    num_gold_snippets: int = 0
    num_retrieved: int = 0


NativeMetrics = TestExecutionMetrics | MatchMetrics | RetrievalMetrics


class EvalResult(BaseModel):
    """The outcome of one (task, model, context_provider, run) evaluation."""

    task_id: str
    provenance: TaskProvenance
    evaluator_kind: EvaluatorKind

    model: str | None
    context_provider: str
    run_index: int

    native_metrics: NativeMetrics = Field(
        discriminator=None,
        description="Typed metrics — always preserves the full native representation.",
    )
    normalized_score: float | None = Field(
        default=None,
        description="Optional convenience score.  Always explain derivation in metadata.",
    )

    generated_output: dict[str, str] = Field(
        default_factory=dict,
        description="Serialised candidate edit: {filename: content} or {'_patch': diff} etc.",
    )
    context_used: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Serialised context snippets that were injected.",
    )

    generation_latency_ms: float = 0.0
    evaluation_latency_ms: float = 0.0

    metadata: dict[str, Any] = Field(default_factory=dict)
