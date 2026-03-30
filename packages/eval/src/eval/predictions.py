from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from eval.generator import PatchGenerator
from eval.prompts import build_baseline_system_message, build_baseline_user_message
from eval.slice import SWEBenchTask

_XML_BLOCK_RE = re.compile(r"\<([\w-]+)\>(.*?)\<\/\1\>", re.DOTALL)
_FENCED_BLOCK_RE = re.compile(r"```(\w+)?\n(.*?)```", re.DOTALL)
_HUNK_HEADER_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@(?P<suffix>.*)$"
)


@dataclass(frozen=True)
class PredictionRecord:
    instance_id: str
    model_name_or_path: str
    model_patch: str
    full_output: str


TaskPromptBuilder = Callable[[SWEBenchTask], str]


def generate_baseline_predictions(
    *,
    tasks: list[SWEBenchTask],
    generator: PatchGenerator,
    output_path: Path,
    overwrite: bool = False,
) -> list[PredictionRecord]:
    return generate_predictions(
        tasks=tasks,
        generator=generator,
        output_path=output_path,
        overwrite=overwrite,
        build_user_message=build_baseline_user_message,
        progress_label="Generating baseline patch for",
    )


def generate_predictions(
    *,
    tasks: list[SWEBenchTask],
    generator: PatchGenerator,
    output_path: Path,
    overwrite: bool = False,
    build_user_message: TaskPromptBuilder,
    progress_label: str,
) -> list[PredictionRecord]:
    if not tasks:
        raise ValueError("No SWE-bench tasks selected for prediction generation.")

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
                print(f"[{index}/{len(tasks)}] {progress_label} {task.instance_id}")
                raw_output = generator.generate_text(
                    system=system_message,
                    user=build_user_message(task),
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
    patch = patch.replace("\r\n", "\n")
    lines = [line for line in patch.split("\n") if line.strip() != "<diff>"]
    if len(lines) >= 2 and lines[0].startswith("a/") and lines[1].startswith("b/"):
        lines = [f"diff --git {lines[0]} {lines[1]}", *lines[2:]]
    patch = _normalize_hunk_headers("\n".join(lines).strip())
    if patch and not patch.endswith("\n"):
        patch += "\n"
    return patch


def _normalize_hunk_headers(patch: str) -> str:
    lines = patch.split("\n")
    normalized: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        match = _HUNK_HEADER_RE.match(line)
        if match is None:
            normalized.append(line)
            index += 1
            continue

        next_index = index + 1
        old_count = 0
        new_count = 0
        body_lines: list[str] = []
        while next_index < len(lines):
            candidate = lines[next_index]
            if candidate.startswith(("diff --git ", "--- ", "+++ ", "@@ ")):
                break
            normalized_candidate = candidate
            if candidate == "":
                normalized_candidate = " "
            elif not candidate.startswith((" ", "+", "-", "\\")):
                normalized_candidate = f" {candidate}"
            body_lines.append(normalized_candidate)
            if normalized_candidate.startswith("\\ No newline at end of file"):
                next_index += 1
                continue
            if normalized_candidate:
                prefix = normalized_candidate[0]
                if prefix in {" ", "-"}:
                    old_count += 1
                if prefix in {" ", "+"}:
                    new_count += 1
            next_index += 1

        suffix = match.group("suffix")
        normalized.append(
            f"@@ -{match.group('old_start')},{old_count} "
            f"+{match.group('new_start')},{new_count} @@{suffix}"
        )
        normalized.extend(body_lines)
        index = next_index

    return "\n".join(normalized)
