from __future__ import annotations

from eval.cli import _build_parser


def test_cli_parses_run_synthetic_matrix_arguments() -> None:
    parser = _build_parser()
    args = parser.parse_args(
        [
            "run-synthetic-matrix",
            "--config",
            "matrix.json",
            "--run-prefix",
            "exp-a",
            "--output-root",
            ".cache/eval/synthetic_experiments/matrix",
            "--dry-run",
            "--continue-on-error",
        ]
    )
    assert args.command == "run-synthetic-matrix"
    assert args.config == "matrix.json"
    assert args.run_prefix == "exp-a"
    assert args.dry_run is True
    assert args.continue_on_error is True
