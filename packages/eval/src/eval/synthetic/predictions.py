from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from eval.generator import PatchGenerator
from eval.predictions import extract_model_patch
from .prompts import (
    build_synthetic_baseline_user_message,
    build_synthetic_system_message,
)
from .workspace import PreparedSyntheticTask


@dataclass(frozen=True)
class SyntheticPredictionRecord:
    task_id: str
    task_type: str
    model_name_or_path: str
    context_source: str
    model_patch: str
    full_output: str


SyntheticPromptBuilder = Callable[[PreparedSyntheticTask], str]


def generate_synthetic_baseline_predictions(
    *,
    tasks: tuple[PreparedSyntheticTask, ...],
    generator: PatchGenerator,
    output_path: Path,
    overwrite: bool = False,
) -> list[SyntheticPredictionRecord]:
    return generate_synthetic_predictions(
        tasks=tasks,
        generator=generator,
        output_path=output_path,
        overwrite=overwrite,
        context_source="baseline",
        build_user_message=build_synthetic_baseline_user_message,
        progress_label="Generating synthetic baseline patch for",
    )


def generate_synthetic_predictions(
    *,
    tasks: tuple[PreparedSyntheticTask, ...],
    generator: PatchGenerator,
    output_path: Path,
    overwrite: bool = False,
    context_source: str,
    build_user_message: SyntheticPromptBuilder,
    progress_label: str,
) -> list[SyntheticPredictionRecord]:
    if not tasks:
        raise ValueError("No synthetic tasks selected for prediction generation.")

    output_path = output_path.resolve()
    if output_path.exists() and not overwrite:
        raise FileExistsError(
            f"Refusing to overwrite existing predictions file: {output_path}"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temp_output_path.unlink(missing_ok=True)

    system_message = build_synthetic_system_message()
    predictions: list[SyntheticPredictionRecord] = []

    try:
        with temp_output_path.open("w", encoding="utf-8") as handle:
            for index, prepared in enumerate(tasks, start=1):
                task = prepared.task
                print(f"[{index}/{len(tasks)}] {progress_label} {task.task_id}")
                raw_output = generator.generate_text(
                    system=system_message,
                    user=build_user_message(prepared),
                )
                model_patch = extract_model_patch(raw_output)

                record = SyntheticPredictionRecord(
                    task_id=task.task_id,
                    task_type=task.task_type,
                    model_name_or_path=generator.model_name,
                    context_source=context_source,
                    model_patch=model_patch,
                    full_output=raw_output,
                )
                handle.write(json.dumps(asdict(record)))
                handle.write("\n")
                handle.flush()

                print(f"    wrote {len(model_patch)} patch chars")
                predictions.append(record)
        temp_output_path.replace(output_path)
    except Exception:
        temp_output_path.unlink(missing_ok=True)
        raise
    return predictions


def load_synthetic_predictions(path: Path) -> dict[str, SyntheticPredictionRecord]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Synthetic predictions file not found: {path}")

    predictions: dict[str, SyntheticPredictionRecord] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        raw_record = json.loads(raw_line)
        if not isinstance(raw_record, dict):
            raise ValueError(f"Expected JSON object on line {line_number} of {path}")
        record = SyntheticPredictionRecord(
            task_id=str(raw_record.get("task_id", "")).strip(),
            task_type=str(raw_record.get("task_type", "")).strip(),
            model_name_or_path=str(raw_record.get("model_name_or_path", "")).strip(),
            context_source=str(raw_record.get("context_source", "")).strip(),
            model_patch=str(raw_record.get("model_patch", "")),
            full_output=str(raw_record.get("full_output", "")),
        )
        if not record.task_id:
            raise ValueError(f"Synthetic prediction on line {line_number} is missing task_id.")
        predictions[record.task_id] = record
    if not predictions:
        raise ValueError(f"Synthetic predictions file is empty: {path}")
    return predictions
