from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from eval.slice import SWEBenchTask


DEFAULT_HARNESS_WORKDIR = Path(".cache/eval/swebench_harness")
DEFAULT_IMAGE_TAG = "latest"
DEFAULT_IMAGE_ARCH = "x86_64"
DEFAULT_RUN_TIMEOUT_SECONDS = 1_800
DEFAULT_CACHE_LEVEL = "env"


@dataclass(frozen=True)
class HarnessEvaluationResult:
    report_path: Path
    run_log_dir: Path


def prepare_swebench_images(
    *,
    tasks: list[SWEBenchTask],
    dataset_name: str,
    split: str,
    workdir: Path = DEFAULT_HARNESS_WORKDIR,
    max_workers: int = 1,
    namespace: str | None = None,
    image_tag: str = DEFAULT_IMAGE_TAG,
    image_arch: str = DEFAULT_IMAGE_ARCH,
) -> list[str]:
    if not tasks:
        raise ValueError("No SWE-bench tasks selected for image preparation.")

    docker_host = resolve_docker_host()
    if not docker_host:
        raise RuntimeError("Could not resolve DOCKER_HOST from the current Docker context.")

    workdir = workdir.resolve()
    logs_root = workdir / "logs" / "build_images"
    logs_root.mkdir(parents=True, exist_ok=True)

    instance_ids = [task.instance_id for task in tasks]
    print(f"Preparing {len(instance_ids)} SWE-bench image(s)")
    print(f"Using Docker endpoint: {docker_host}")
    print(f"Harness workdir: {workdir}")
    print("Instance ids:")
    for instance_id in instance_ids:
        print(f"  - {instance_id}")

    env = os.environ.copy()
    env["DOCKER_HOST"] = docker_host
    if "HF_TOKEN" not in env and env.get("HUGGINGFACE_HUB_TOKEN"):
        env["HF_TOKEN"] = env["HUGGINGFACE_HUB_TOKEN"]

    command = [
        sys.executable,
        "-m",
        "swebench.harness.prepare_images",
        "--dataset_name",
        dataset_name,
        "--split",
        split,
        "--instance_ids",
        *instance_ids,
        "--max_workers",
        str(max_workers),
        "--tag",
        image_tag,
        "--env_image_tag",
        image_tag,
        "--namespace",
        "none" if namespace is None else namespace,
    ]

    stop_event = threading.Event()
    streamer = threading.Thread(
        target=_stream_harness_logs,
        args=(logs_root, stop_event, _existing_log_paths(logs_root)),
        daemon=True,
    )
    streamer.start()

    try:
        result = subprocess.run(
            command,
            cwd=workdir,
            env=env,
            check=False,
        )
    finally:
        stop_event.set()
        streamer.join(timeout=2.0)

    if result.returncode != 0:
        raise RuntimeError(f"SWE-bench image preparation failed with exit code {result.returncode}.")

    expected_images = [
        swebench_image_name(
            task.instance_id,
            namespace=namespace,
            image_tag=image_tag,
            image_arch=image_arch,
        )
        for task in tasks
    ]
    verify_docker_images(expected_images)
    return expected_images


def evaluate_swebench_predictions(
    *,
    tasks: list[SWEBenchTask],
    dataset_name: str,
    split: str,
    predictions_path: Path,
    run_id: str,
    workdir: Path = DEFAULT_HARNESS_WORKDIR,
    max_workers: int = 1,
    timeout_seconds: int = DEFAULT_RUN_TIMEOUT_SECONDS,
    cache_level: str = DEFAULT_CACHE_LEVEL,
    image_tag: str = DEFAULT_IMAGE_TAG,
) -> HarnessEvaluationResult:
    if not tasks:
        raise ValueError("No SWE-bench tasks selected for evaluation.")
    if not run_id.strip():
        raise ValueError("run_id must not be empty.")
    if max_workers < 1:
        raise ValueError("max_workers must be at least 1.")
    if timeout_seconds < 1:
        raise ValueError("timeout_seconds must be at least 1.")
    if cache_level not in {"none", "base", "env", "instance"}:
        raise ValueError("cache_level must be one of: none, base, env, instance")

    predictions_path = predictions_path.resolve()
    if not predictions_path.is_file():
        raise FileNotFoundError(f"Predictions file not found: {predictions_path}")

    docker_host = resolve_docker_host()
    if not docker_host:
        raise RuntimeError("Could not resolve DOCKER_HOST from the current Docker context.")

    workdir = workdir.resolve()
    logs_root = workdir / "logs"
    logs_root.mkdir(parents=True, exist_ok=True)

    instance_ids = [task.instance_id for task in tasks]
    model_name = read_prediction_model_name(predictions_path)
    model_dir_name = model_name.replace("/", "__")

    print(f"Evaluating {len(instance_ids)} SWE-bench prediction(s)")
    print(f"Run id: {run_id}")
    print(f"Using Docker endpoint: {docker_host}")
    print(f"Harness workdir: {workdir}")
    print(f"Predictions file: {predictions_path}")
    print("Instance ids:")
    for instance_id in instance_ids:
        print(f"  - {instance_id}")

    env = os.environ.copy()
    env["DOCKER_HOST"] = docker_host
    if "HF_TOKEN" not in env and env.get("HUGGINGFACE_HUB_TOKEN"):
        env["HF_TOKEN"] = env["HUGGINGFACE_HUB_TOKEN"]

    command = [
        sys.executable,
        "-m",
        "swebench.harness.run_evaluation",
        "--dataset_name",
        dataset_name,
        "--split",
        split,
        "--instance_ids",
        *instance_ids,
        "--predictions_path",
        str(predictions_path),
        "--max_workers",
        str(max_workers),
        "--timeout",
        str(timeout_seconds),
        "--cache_level",
        cache_level,
        "--run_id",
        run_id,
        "--namespace",
        "none",
        "--instance_image_tag",
        image_tag,
        "--env_image_tag",
        image_tag,
    ]

    stop_event = threading.Event()
    streamer = threading.Thread(
        target=_stream_harness_logs,
        args=(logs_root, stop_event, _existing_log_paths(logs_root)),
        daemon=True,
    )
    streamer.start()

    try:
        result = subprocess.run(
            command,
            cwd=workdir,
            env=env,
            check=False,
        )
    finally:
        stop_event.set()
        streamer.join(timeout=2.0)

    if result.returncode != 0:
        raise RuntimeError(f"SWE-bench evaluation failed with exit code {result.returncode}.")

    report_path = workdir / f"{model_dir_name}.{run_id}.json"
    if not report_path.is_file():
        raise RuntimeError(f"Expected evaluation report is missing: {report_path}")

    run_log_dir = workdir / "logs" / "run_evaluation" / run_id / model_dir_name
    return HarnessEvaluationResult(
        report_path=report_path,
        run_log_dir=run_log_dir,
    )


def resolve_docker_host() -> str | None:
    if os.environ.get("DOCKER_HOST"):
        return os.environ["DOCKER_HOST"]

    result = subprocess.run(
        [
            "docker",
            "context",
            "inspect",
            "--format",
            '{{ (index .Endpoints "docker").Host }}',
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def swebench_image_name(
    instance_id: str,
    *,
    namespace: str | None,
    image_tag: str,
    image_arch: str,
) -> str:
    name = f"sweb.eval.{image_arch}.{instance_id.lower()}:{image_tag}"
    if namespace:
        return f"{namespace}/{name}"
    return name


def verify_docker_images(image_names: Iterable[str]) -> None:
    for image_name in image_names:
        result = subprocess.run(
            ["docker", "image", "inspect", image_name],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Expected Docker image is missing: {image_name}")
        print(f"Verified image: {image_name}")


def read_prediction_model_name(predictions_path: Path) -> str:
    if predictions_path.suffix == ".jsonl":
        for line in predictions_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            model_name = row.get("model_name_or_path")
            if isinstance(model_name, str) and model_name.strip():
                return model_name
    elif predictions_path.suffix == ".json":
        data = json.loads(predictions_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            for row in data:
                if not isinstance(row, dict):
                    continue
                model_name = row.get("model_name_or_path")
                if isinstance(model_name, str) and model_name.strip():
                    return model_name
        elif isinstance(data, dict):
            for row in data.values():
                if not isinstance(row, dict):
                    continue
                model_name = row.get("model_name_or_path")
                if isinstance(model_name, str) and model_name.strip():
                    return model_name

    raise ValueError(
        f"Could not determine model_name_or_path from predictions file: {predictions_path}"
    )


def _stream_harness_logs(
    logs_root: Path,
    stop_event: threading.Event,
    initial_seen: set[Path] | None = None,
) -> None:
    seen: set[Path] = set(initial_seen or set())
    tailers: list[threading.Thread] = []

    while not stop_event.is_set():
        for log_path in sorted(logs_root.rglob("*.log")):
            if log_path in seen:
                continue
            seen.add(log_path)
            relative = log_path.relative_to(logs_root)
            print(f"Streaming harness log: {relative}")
            tailer = threading.Thread(
                target=_tail_log_file,
                args=(logs_root, log_path, stop_event),
                daemon=True,
            )
            tailer.start()
            tailers.append(tailer)
        stop_event.wait(1.0)

    for tailer in tailers:
        tailer.join(timeout=1.0)


def _existing_log_paths(logs_root: Path) -> set[Path]:
    if not logs_root.exists():
        return set()
    return set(logs_root.rglob("*.log"))


def _tail_log_file(logs_root: Path, log_path: Path, stop_event: threading.Event) -> None:
    prefix = log_path.relative_to(logs_root)
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            while True:
                line = handle.readline()
                if line:
                    print(f"[harness:{prefix}] {line.rstrip()}")
                    continue
                if stop_event.is_set():
                    break
                stop_event.wait(0.5)

            while True:
                line = handle.readline()
                if not line:
                    break
                print(f"[harness:{prefix}] {line.rstrip()}")
    except FileNotFoundError:
        return
