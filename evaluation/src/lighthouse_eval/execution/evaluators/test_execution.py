from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from lighthouse_eval.candidates.base import _CandidateBase
from lighthouse_eval.datasets.schema import (
    EvaluatorKind,
    Task,
    TestExecutionMetrics,
)

log = logging.getLogger(__name__)


class PytestEvaluator:
    """Run pytest in a workspace and parse a JSON report."""

    kind = EvaluatorKind.test_execution

    async def evaluate(
        self, task: Task, candidate: _CandidateBase, workspace: Path
    ) -> TestExecutionMetrics:
        spec = task.test_spec
        if spec is None:
            raise ValueError(f"Task {task.id} has no test_spec for PytestEvaluator")

        report_path = workspace / ".report.json"

        cmd_parts: list[str] = []
        if spec.test_commands:
            cmd_parts = [spec.test_commands[0]]
        else:
            test_targets = " ".join(str(p) for p in spec.test_paths) if spec.test_paths else "."
            cmd_parts = [
                "python", "-m", "pytest",
                test_targets,
                "-q", "--tb=short",
                f"--json-report", f"--json-report-file={report_path}",
            ]

        cmd_str = " ".join(cmd_parts)
        log.info("Running: %s  (cwd=%s, timeout=%ss)", cmd_str, workspace, spec.timeout_seconds)

        proc = await asyncio.create_subprocess_shell(
            cmd_str,
            cwd=workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(
                proc.communicate(), timeout=spec.timeout_seconds
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            log.warning("Pytest timed out after %ss for task %s", spec.timeout_seconds, task.id)
            return TestExecutionMetrics()

        if report_path.exists():
            return self._parse_json_report(report_path)

        return self._parse_stdout(stdout.decode(errors="replace"))

    @staticmethod
    def _parse_json_report(report_path: Path) -> TestExecutionMetrics:
        data = json.loads(report_path.read_text(encoding="utf-8"))
        summary = data.get("summary", {})
        passed = summary.get("passed", 0)
        failed = summary.get("failed", 0)
        errors = summary.get("error", 0)
        total = summary.get("total", passed + failed + errors)
        return TestExecutionMetrics(
            passed=passed,
            failed=failed,
            errors=errors,
            total=total,
            pass_rate=passed / total if total > 0 else 0.0,
        )

    @staticmethod
    def _parse_stdout(stdout: str) -> TestExecutionMetrics:
        """Best-effort fallback when the JSON report plugin is unavailable."""
        passed = failed = errors = 0
        for line in reversed(stdout.splitlines()):
            low = line.lower()
            if "passed" in low or "failed" in low or "error" in low:
                import re

                for m in re.finditer(r"(\d+)\s+(passed|failed|error)", low):
                    count = int(m.group(1))
                    kind = m.group(2)
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
