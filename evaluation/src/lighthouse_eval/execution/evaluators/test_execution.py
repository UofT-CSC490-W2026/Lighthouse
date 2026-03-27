from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import shutil
from pathlib import Path

from lighthouse_eval.candidates.base import _CandidateBase
from lighthouse_eval.datasets.schema import EvaluatorKind, Task, TestExecutionMetrics, TestSpec

log = logging.getLogger(__name__)


class PytestEvaluator:
    """Run a task's declared execution backend and parse pytest results when available."""

    kind = EvaluatorKind.test_execution

    async def evaluate(
        self, task: Task, candidate: _CandidateBase, workspace: Path
    ) -> TestExecutionMetrics:
        spec = task.test_spec
        if spec is None:
            raise ValueError(f"Task {task.id} has no test_spec for PytestEvaluator")

        if (
            spec.execution_backend in {"docker_pytest", "command_sequence"}
            and task.workspace_path is None
        ):
            raise RuntimeError(
                f"Task {task.id} uses execution_backend={spec.execution_backend!r} "
                "but has no materialized workspace_path. Materialize the benchmark "
                "workspace before running this task."
            )

        local_test_paths = self._materialize_test_paths(spec.test_paths, workspace)
        commands, report_paths = self._build_commands(
            task=task,
            workspace=workspace,
            local_test_paths=local_test_paths,
        )

        reports: list[dict] = []
        last_stdout = ""
        last_stderr = ""
        for command, report_path in zip(commands, report_paths):
            log.info(
                "Running (%s): %s  (cwd=%s, timeout=%ss)",
                spec.execution_backend,
                command,
                workspace,
                spec.timeout_seconds,
            )
            try:
                if spec.execution_backend == "docker_pytest":
                    stdout, stderr, returncode = await self._run_docker_command(
                        command=command,
                        workspace=workspace,
                        docker_image=spec.docker_image,
                        timeout_seconds=spec.timeout_seconds,
                    )
                else:
                    stdout, stderr, returncode = await self._run_local_command(
                        command=command,
                        workspace=workspace,
                        timeout_seconds=spec.timeout_seconds,
                    )
            except asyncio.TimeoutError:
                log.warning("Pytest timed out after %ss for task %s", spec.timeout_seconds, task.id)
                return TestExecutionMetrics()

            last_stdout = stdout
            last_stderr = stderr

            report = self._load_json_report(workspace, report_path)
            if report is not None:
                reports.append(report)

            if returncode != 0:
                break

        if reports:
            return self._aggregate_reports(reports, spec)

        log.debug("No JSON report produced for task %s. stderr=%s", task.id, last_stderr[:500])
        return self._parse_stdout(last_stdout)

    def _build_commands(
        self,
        *,
        task: Task,
        workspace: Path,
        local_test_paths: list[Path],
    ) -> tuple[list[str], list[Path | None]]:
        spec = task.test_spec
        if spec is None:
            raise ValueError(f"Task {task.id} has no test_spec for PytestEvaluator")

        commands = list(spec.test_commands)
        if not commands:
            if spec.execution_backend not in {"local_pytest", "docker_pytest"}:
                raise ValueError(
                    f"Task {task.id} requires explicit test_commands for "
                    f"execution_backend={spec.execution_backend!r}."
                )

            test_targets = [str(path) for path in local_test_paths] if local_test_paths else ["."]
            commands = [
                self._default_pytest_command(
                    test_targets=test_targets,
                    report_path=Path(".report_0.json"),
                )
            ]

        resolved_commands: list[str] = []
        report_paths: list[Path | None] = []
        for index, command in enumerate(commands):
            default_report = Path(f".report_{index}.json")
            if spec.execution_backend in {"local_pytest", "docker_pytest"}:
                command, report_path = self._ensure_pytest_json_reporting(command, default_report)
            elif spec.execution_backend == "command_sequence" and "pytest" in command:
                command, report_path = self._ensure_pytest_json_reporting(command, default_report)
            else:
                report_path = None

            resolved_commands.append(command)
            report_paths.append(report_path)

        return resolved_commands, report_paths

    @staticmethod
    def _default_pytest_command(*, test_targets: list[str], report_path: Path) -> str:
        targets = " ".join(shlex.quote(target) for target in test_targets)
        return (
            f"python -m pytest {targets} -q --tb=short "
            f"--json-report --json-report-file={shlex.quote(str(report_path))}"
        )

    @staticmethod
    def _ensure_pytest_json_reporting(command: str, report_path: Path) -> tuple[str, Path]:
        if "pytest" not in command:
            raise ValueError(
                "local_pytest and docker_pytest backends require pytest-based commands."
            )

        report_match = re.search(r"--json-report-file(?:=|\s+)(\S+)", command)
        if report_match:
            existing_path = report_match.group(1).strip("'\"")
            return command, Path(existing_path)

        if "--json-report" in command:
            return command + f" --json-report-file={shlex.quote(str(report_path))}", report_path

        return (
            command
            + f" --json-report --json-report-file={shlex.quote(str(report_path))}",
            report_path,
        )

    @staticmethod
    async def _run_local_command(
        *,
        command: str,
        workspace: Path,
        timeout_seconds: int,
    ) -> tuple[str, str, int]:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise
        returncode = proc.returncode
        if returncode is None:
            raise RuntimeError("Local test command exited without a return code.")
        return stdout.decode(errors="replace"), stderr.decode(errors="replace"), returncode

    @staticmethod
    async def _run_docker_command(
        *,
        command: str,
        workspace: Path,
        docker_image: str | None,
        timeout_seconds: int,
    ) -> tuple[str, str, int]:
        if not docker_image:
            raise ValueError("docker_pytest requires docker_image to be set.")

        proc = await asyncio.create_subprocess_exec(
            "docker",
            "run",
            "--rm",
            "-v",
            f"{workspace.resolve()}:/workspace",
            "-w",
            "/workspace",
            docker_image,
            "sh",
            "-lc",
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise
        returncode = proc.returncode
        if returncode is None:
            raise RuntimeError("Docker test command exited without a return code.")
        return stdout.decode(errors="replace"), stderr.decode(errors="replace"), returncode

    @staticmethod
    def _materialize_test_paths(test_paths: list[Path], workspace: Path) -> list[Path]:
        if not test_paths:
            return []

        materialized: list[Path] = []
        absolute_roots: list[Path] = []
        for path in test_paths:
            if path.is_absolute():
                absolute_roots.append(path if path.is_dir() else path.parent)

        common_root: Path | None = None
        if absolute_roots:
            common_root = Path(os.path.commonpath([str(root) for root in absolute_roots]))

        dest_root = workspace / ".lheval_tests"
        for path in test_paths:
            if path.is_absolute():
                if not path.exists():
                    continue
                rel = path.relative_to(common_root) if common_root else Path(path.name)
                dest = dest_root / rel
                if path.is_dir():
                    shutil.copytree(path, dest, dirs_exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, dest)
                materialized.append(dest.relative_to(workspace))
            else:
                materialized.append(path)

        return materialized

    @staticmethod
    def _load_json_report(workspace: Path, report_path: Path | None) -> dict | None:
        if report_path is None:
            return None

        path = report_path if report_path.is_absolute() else workspace / report_path
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _aggregate_reports(reports: list[dict], spec: TestSpec) -> TestExecutionMetrics:
        passed = failed = errors = total = 0
        outcomes: dict[str, str] = {}

        for report in reports:
            summary = report.get("summary", {})
            passed += int(summary.get("passed", 0))
            failed += int(summary.get("failed", 0))
            errors += int(summary.get("error", summary.get("errors", 0)))
            total += int(summary.get("total", 0))

            for test_case in report.get("tests", []):
                nodeid = test_case.get("nodeid")
                outcome = test_case.get("outcome")
                if isinstance(nodeid, str) and isinstance(outcome, str):
                    outcomes[nodeid] = outcome

        if total == 0:
            total = passed + failed + errors

        fail_to_pass_resolved = None
        if spec.expected_to_pass:
            fail_to_pass_resolved = sum(
                1 for nodeid in spec.expected_to_pass if outcomes.get(nodeid) == "passed"
            )

        pass_to_pass_preserved = None
        if spec.expected_to_stay_passing:
            pass_to_pass_preserved = sum(
                1
                for nodeid in spec.expected_to_stay_passing
                if outcomes.get(nodeid) == "passed"
            )

        return TestExecutionMetrics(
            passed=passed,
            failed=failed,
            errors=errors,
            total=total,
            pass_rate=passed / total if total > 0 else 0.0,
            fail_to_pass_resolved=fail_to_pass_resolved,
            pass_to_pass_preserved=pass_to_pass_preserved,
        )

    @staticmethod
    def _parse_stdout(stdout: str) -> TestExecutionMetrics:
        """Best-effort fallback when the JSON report plugin is unavailable."""
        passed = failed = errors = 0
        for line in reversed(stdout.splitlines()):
            low = line.lower()
            if "passed" in low or "failed" in low or "error" in low:
                for match in re.finditer(r"(\d+)\s+(passed|failed|error)", low):
                    count = int(match.group(1))
                    kind = match.group(2)
                    if kind == "passed":
                        passed = count
                    elif kind == "failed":
                        failed = count
                    elif kind == "error":
                        errors = count
                break
        total = passed + failed + errors
        return TestExecutionMetrics(
            passed=passed,
            failed=failed,
            errors=errors,
            total=total,
            pass_rate=passed / total if total > 0 else 0.0,
        )
