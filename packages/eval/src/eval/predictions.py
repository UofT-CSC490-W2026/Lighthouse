from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from eval.bedrock import BedrockPatchGenerator
from eval.prompts import build_baseline_system_message, build_baseline_user_message
from eval.slice import SWEBenchTask

_XML_BLOCK_RE = re.compile(r"\<([\w-]+)\>(.*?)\<\/\1\>", re.DOTALL)
_FENCED_BLOCK_RE = re.compile(r"```(\w+)?\n(.*?)```", re.DOTALL)


@dataclass(frozen=True)
class PredictionRecord:
    instance_id: str
    model_name_or_path: str
    model_patch: str
    full_output: str


def generate_baseline_predictions(
    *,
    tasks: list[SWEBenchTask],
    generator: BedrockPatchGenerator,
    output_path: Path,
    overwrite: bool = False,
) -> list[PredictionRecord]:
    if not tasks:
        raise ValueError("No SWE-bench tasks selected for baseline generation.")

    output_path = output_path.resolve()
    if output_path.exists() and not overwrite:
        raise FileExistsError(
            f"Refusing to overwrite existing predictions file: {output_path}"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temp_output_path.unlink(missing_ok=True)

    system_message = build_baseline_system_message()
    predictions: list[PredictionRecord] = []

    try:
        with temp_output_path.open("w", encoding="utf-8") as handle:
            for index, task in enumerate(tasks, start=1):
                print(f"[{index}/{len(tasks)}] Generating baseline patch for {task.instance_id}")
                raw_output = generator.generate_text(
                    system=system_message,
                    user=build_baseline_user_message(task),
                )
                model_patch = extract_model_patch(raw_output)

                record = PredictionRecord(
                    instance_id=task.instance_id,
                    model_name_or_path=generator.model_name,
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


def extract_model_patch(response: str | None) -> str:
    if response is None:
        return ""

    response = response.strip()
    if not response:
        return ""

    diff_matches: list[str] = []
    other_matches: list[str] = []

    for code, match in _XML_BLOCK_RE.findall(response):
        if code in {"diff", "patch"}:
            diff_matches.append(match)
        else:
            other_matches.append(match)

    for code, match in _FENCED_BLOCK_RE.findall(response):
        if code in {"diff", "patch"}:
            diff_matches.append(match)
        else:
            other_matches.append(match)

    if diff_matches:
        return _normalize_patch_text(diff_matches[0])
    if other_matches:
        return _normalize_patch_text(other_matches[0])
    return _normalize_patch_text(response.split("</s>")[0])


def _normalize_patch_text(text: str) -> str:
    patch = text.strip()
    if patch and not patch.endswith("\n"):
        patch += "\n"
    return patch
