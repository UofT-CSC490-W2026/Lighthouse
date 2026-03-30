from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from eval.synthetic.matrix import (
    expand_matrix_cell_specs,
    load_synthetic_matrix_config,
    run_synthetic_matrix,
)


@pytest.mark.unit
def test_load_synthetic_matrix_config_and_expand_cells(tmp_path: Path) -> None:
    config_path = tmp_path / "matrix.json"
    config_path.write_text(
        json.dumps(
            {
                "families": ["synthetic-ab-contracts"],
                "context_sources": ["code", "wiki"],
                "chunking_strategies": ["base", "ast"],
                "codegen_models": ["bedrock/us.amazon.nova-pro-v1:0", "openai/gpt-5.4"],
                "embedding_models": [
                    "amazon.titan-embed-text-v2:0",
                    "text-embedding-3-large",
                ],
                "embedding_strategy": "openai",
                "repeat_count": 2,
                "k_values": [1, 3],
            }
        ),
        encoding="utf-8",
    )
    config = load_synthetic_matrix_config(config_path)
    specs = expand_matrix_cell_specs(config=config)
    assert len(specs) == 16
    assert config.repeat_count == 2
    assert config.k_values == (1, 3)


@pytest.mark.unit
def test_run_synthetic_matrix_dry_run_writes_plan_artifacts(tmp_path: Path) -> None:
    config_path = tmp_path / "matrix.json"
    config_path.write_text(
        json.dumps(
            {
                "families": ["synthetic-ab-contracts"],
                "context_sources": ["code"],
                "chunking_strategies": ["base"],
                "codegen_models": ["openai/gpt-5.4"],
                "embedding_models": ["text-embedding-3-large"],
                "embedding_strategy": "openai",
                "repeat_count": 2,
                "k_values": [1, 2],
            }
        ),
        encoding="utf-8",
    )
    config = load_synthetic_matrix_config(config_path)
    result = run_synthetic_matrix(
        config=config,
        run_prefix="matrix-smoke",
        output_root=tmp_path / "out",
        workspace_root=tmp_path / "workspace",
        dry_run=True,
    )
    assert result.rows_json_path.is_file()
    assert result.rows_markdown_path.is_file()
    assert result.efficiency_json_path.is_file()
    assert result.efficiency_text_path.is_file()
    rows_text = result.rows_markdown_path.read_text(encoding="utf-8")
    assert "Scores and Pass@k" in rows_text
    assert "Efficiency" in rows_text
    assert result.heatmap_paths == ()
    assert len(result.cell_results) == 1
    assert len(result.cell_results[0].run_ids) == 2


@pytest.mark.unit
def test_run_synthetic_matrix_collects_pass_at_k_and_score(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "matrix.json"
    config_path.write_text(
        json.dumps(
            {
                "families": ["synthetic-ab-contracts"],
                "context_sources": ["code"],
                "chunking_strategies": ["base"],
                "codegen_models": ["openai/gpt-5.4"],
                "embedding_models": ["text-embedding-3-large"],
                "embedding_strategy": "openai",
                "repeat_count": 2,
                "k_values": [1, 2],
            }
        ),
        encoding="utf-8",
    )
    config = load_synthetic_matrix_config(config_path)

    run_counter = {"count": 0}

    def fake_run_synthetic_experiment(**kwargs: object):
        run_counter["count"] += 1
        assert kwargs["model_name"] == "openai/gpt-5.4"
        assert kwargs["indexing_embedding_model"] == "text-embedding-3-large"
        resolved = 1 if run_counter["count"] == 1 else 0
        return SimpleNamespace(
            lighthouse_summary=SimpleNamespace(
                run_id=f"run-{run_counter['count']}-code",
                total_instances=2,
                resolved_instances=resolved,
            ),
            baseline_summary=SimpleNamespace(run_id=f"run-{run_counter['count']}-baseline"),
            lighthouse_efficiency=SimpleNamespace(
                total_duration_seconds=3.0,
                generation=SimpleNamespace(
                    total_tokens=400,
                    estimated_cost_usd=0.012,
                ),
            ),
        )

    def fake_compute_pass_at_k(**kwargs: object):
        assert kwargs["run_ids"] == ["run-1-code", "run-2-code"]
        return SimpleNamespace(macro_pass_at_k=((1, 0.5), (2, 1.0)))

    monkeypatch.setattr("eval.synthetic.matrix.run_synthetic_experiment", fake_run_synthetic_experiment)
    monkeypatch.setattr("eval.synthetic.matrix.compute_synthetic_pass_at_k", fake_compute_pass_at_k)
    monkeypatch.setattr(
        "eval.synthetic.matrix.render_synthetic_pass_at_k_table",
        lambda summary: "pass-at-k",
    )
    monkeypatch.setattr("eval.synthetic.matrix._render_heatmaps", lambda rows, config, output_root: ())

    result = run_synthetic_matrix(
        config=config,
        run_prefix="matrix-real",
        output_root=tmp_path / "out",
        workspace_root=tmp_path / "workspace",
        dry_run=False,
    )
    assert len(result.cell_results) == 1
    cell = result.cell_results[0]
    assert cell.repeat_scores_pct == (50.0, 0.0)
    assert cell.mean_score_pct == pytest.approx(25.0)
    assert dict(cell.pass_at_k)[1] == pytest.approx(0.5)
    assert dict(cell.pass_at_k)[2] == pytest.approx(1.0)
    assert cell.pass_at_k_table_path is not None
    assert cell.pass_at_k_table_path.is_file()
    assert cell.mean_total_duration_seconds == pytest.approx(3.0)
    assert cell.mean_generation_total_tokens == pytest.approx(400.0)
    assert cell.mean_generation_cost_usd == pytest.approx(0.012)
