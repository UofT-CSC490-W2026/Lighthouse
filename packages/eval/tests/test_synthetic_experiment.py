from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from eval.synthetic import PreparedSyntheticWorkspace
from eval.synthetic.experiment import (
    run_synthetic_experiment,
    run_synthetic_experiment_suite,
)
from eval.synthetic.predictions import SyntheticPredictionRecord


@pytest.mark.integration
def test_run_synthetic_experiment_writes_comparison_and_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_index_kwargs: dict[str, object] = {}
    observed_wiki_kwargs: dict[str, object] = {}
    observed_lighthouse_kwargs: dict[str, object] = {}

    def fake_index_synthetic_repository(**kwargs: object) -> Path:
        observed_index_kwargs.update(kwargs)
        workspace = kwargs["workspace"]
        assert isinstance(workspace, PreparedSyntheticWorkspace)
        assert kwargs["include_ast"] is False
        return workspace.repo_registry_path

    def fake_prepare_synthetic_wiki(**kwargs: object) -> None:
        observed_wiki_kwargs.update(kwargs)

    def write_prediction_file(
        *,
        tasks,
        generator,
        output_path: Path,
        overwrite: bool,
        context_source: str,
        **_: object,
    ) -> None:
        _ = generator
        if output_path.exists() and not overwrite:
            raise FileExistsError(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        records = [
            SyntheticPredictionRecord(
                task_id=prepared.task.task_id,
                task_type=prepared.task.task_type,
                model_name_or_path="bedrock/us.amazon.nova-pro-v1:0",
                context_source=context_source,
                model_patch=prepared.task.gold_patch_path.read_text(encoding="utf-8"),
                full_output=prepared.task.gold_patch_path.read_text(encoding="utf-8"),
            )
            for prepared in tasks
        ]
        output_path.write_text(
            "\n".join(json.dumps(asdict(record)) for record in records) + "\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(
        "eval.synthetic.experiment.index_synthetic_repository",
        fake_index_synthetic_repository,
    )
    monkeypatch.setattr(
        "eval.synthetic.experiment.prepare_synthetic_wiki",
        fake_prepare_synthetic_wiki,
    )
    monkeypatch.setattr(
        "eval.synthetic.experiment.build_synthetic_lighthouse_messages",
        lambda **kwargs: observed_lighthouse_kwargs.update(kwargs)
        or {
            prepared.task.task_id: "synthetic retrieval context"
            for prepared in kwargs["workspace"].tasks
        },
    )
    monkeypatch.setattr(
        "eval.synthetic.experiment.generate_synthetic_baseline_predictions",
        lambda **kwargs: write_prediction_file(context_source="baseline", **kwargs),
    )
    monkeypatch.setattr(
        "eval.synthetic.experiment.generate_synthetic_predictions",
        lambda **kwargs: write_prediction_file(**kwargs),
    )

    class FakeGenerator:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    monkeypatch.setattr(
        "eval.synthetic.experiment.BedrockPatchGenerator", FakeGenerator
    )

    result = run_synthetic_experiment(
        family_name="synthetic-ab-contracts",
        task_count=1,
        task_type=None,
        seed=5,
        shared_library_repo_count=None,
        workspace_root=tmp_path / "workspace",
        force_workspace=True,
        run_prefix="smoke",
        predictions_root=tmp_path / "predictions",
        runs_root=tmp_path / "runs",
        artifacts_root=tmp_path / "artifacts",
        overwrite=True,
        validate_workspace=True,
        skip_index=False,
        skip_wiki_preparation=True,
        ingestion_url="http://localhost:8001",
        search_service_url="http://localhost:8002",
        context_source="code",
        top_k=2,
        github_token=None,
        stream_worker_logs=False,
        index_poll_interval_seconds=1.0,
        index_progress_heartbeat_seconds=1.0,
        index_timeout_seconds=30.0,
        wiki_poll_interval_seconds=1.0,
        wiki_progress_heartbeat_seconds=1.0,
        wiki_timeout_seconds=30.0,
        model_name="bedrock/us.amazon.nova-pro-v1:0",
        region_name="us-east-1",
        temperature=0.0,
        max_tokens=1024,
        indexing_embedding_strategy="bedrock",
        indexing_embedding_model="amazon.titan-embed-text-v2:0",
        query_embedding_strategy="openai",
        query_embedding_model="text-embedding-3-large",
    )

    assert result.baseline_summary.resolved_instances == 1
    assert result.lighthouse_summary.resolved_instances == 1
    assert result.baseline_summary.experiment.generation_model_name_or_path == (
        "bedrock/us.amazon.nova-pro-v1:0"
    )
    assert result.lighthouse_summary.experiment.search_top_k == 2
    assert result.comparison_text_path.is_file()
    assert result.comparison_json_path.is_file()
    assert result.report_path.is_file()
    assert observed_index_kwargs["embedding_strategy"] == "bedrock"
    assert observed_index_kwargs["embedding_model"] == "amazon.titan-embed-text-v2:0"
    assert observed_lighthouse_kwargs["query_embedding_strategy"] == "openai"
    assert observed_lighthouse_kwargs["query_embedding_model"] == "text-embedding-3-large"


@pytest.mark.integration
def test_run_synthetic_experiment_suite_writes_score_table_and_reports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_wiki_kwargs: dict[str, object] = {}

    def fake_index_synthetic_repository(**kwargs: object) -> Path:
        workspace = kwargs["workspace"]
        assert isinstance(workspace, PreparedSyntheticWorkspace)
        assert kwargs["include_ast"] is True
        return workspace.repo_registry_path

    def fake_prepare_synthetic_wiki(**kwargs: object) -> None:
        observed_wiki_kwargs.update(kwargs)

    def write_prediction_file(
        *,
        tasks,
        generator,
        output_path: Path,
        overwrite: bool,
        context_source: str,
        **_: object,
    ) -> None:
        _ = generator
        if output_path.exists() and not overwrite:
            raise FileExistsError(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        records = [
            SyntheticPredictionRecord(
                task_id=prepared.task.task_id,
                task_type=prepared.task.task_type,
                model_name_or_path="bedrock/us.amazon.nova-pro-v1:0",
                context_source=context_source,
                model_patch=prepared.task.gold_patch_path.read_text(encoding="utf-8"),
                full_output=prepared.task.gold_patch_path.read_text(encoding="utf-8"),
            )
            for prepared in tasks
        ]
        output_path.write_text(
            "\n".join(json.dumps(asdict(record)) for record in records) + "\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(
        "eval.synthetic.experiment.index_synthetic_repository",
        fake_index_synthetic_repository,
    )
    monkeypatch.setattr(
        "eval.synthetic.experiment.prepare_synthetic_wiki",
        fake_prepare_synthetic_wiki,
    )
    monkeypatch.setattr(
        "eval.synthetic.experiment.build_synthetic_lighthouse_messages",
        lambda **kwargs: {
            prepared.task.task_id: f"{kwargs['context_source']} retrieval context"
            for prepared in kwargs["workspace"].tasks
        },
    )
    monkeypatch.setattr(
        "eval.synthetic.experiment.generate_synthetic_baseline_predictions",
        lambda **kwargs: write_prediction_file(context_source="baseline", **kwargs),
    )
    monkeypatch.setattr(
        "eval.synthetic.experiment.generate_synthetic_predictions",
        lambda **kwargs: write_prediction_file(**kwargs),
    )

    class FakeGenerator:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    monkeypatch.setattr(
        "eval.synthetic.experiment.BedrockPatchGenerator", FakeGenerator
    )

    result = run_synthetic_experiment_suite(
        family_name="synthetic-ab-contracts",
        task_count=1,
        task_type=None,
        seed=5,
        shared_library_repo_count=None,
        workspace_root=tmp_path / "workspace",
        force_workspace=True,
        run_prefix="smoke-all",
        predictions_root=tmp_path / "predictions",
        runs_root=tmp_path / "runs",
        artifacts_root=tmp_path / "artifacts",
        overwrite=True,
        validate_workspace=True,
        skip_index=False,
        skip_wiki_preparation=False,
        ingestion_url="http://localhost:8001",
        search_service_url="http://localhost:8002",
        top_k=2,
        github_token=None,
        stream_worker_logs=False,
        index_poll_interval_seconds=1.0,
        index_progress_heartbeat_seconds=1.0,
        index_timeout_seconds=30.0,
        wiki_poll_interval_seconds=1.0,
        wiki_progress_heartbeat_seconds=1.0,
        wiki_timeout_seconds=30.0,
        model_name="bedrock/us.amazon.nova-pro-v1:0",
        region_name="us-east-1",
        temperature=0.0,
        max_tokens=1024,
    )

    assert result.baseline_summary.resolved_instances == 1
    assert result.lighthouse_summaries["code"].resolved_instances == 1
    assert result.lighthouse_summaries["wiki"].resolved_instances == 1
    assert result.lighthouse_summaries["ast"].resolved_instances == 1
    assert result.lighthouse_summaries["combined"].resolved_instances == 1
    assert [row.label for row in result.score_rows] == [
        "baseline",
        "code",
        "wiki",
        "ast",
        "combined",
    ]
    assert result.score_text_path.is_file()
    assert result.score_json_path.is_file()
    assert result.comparison_text_paths["code"].is_file()
    assert result.comparison_text_paths["wiki"].is_file()
    assert observed_wiki_kwargs["embedding_strategy"] is None
    assert observed_wiki_kwargs["embedding_model"] is None
    assert result.comparison_text_paths["ast"].is_file()
    assert result.comparison_text_paths["combined"].is_file()
    assert result.report_path.is_file()
