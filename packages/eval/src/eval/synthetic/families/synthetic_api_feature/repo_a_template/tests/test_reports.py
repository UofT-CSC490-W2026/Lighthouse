from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consumer_app.reports import storage_report, tag_line, task_summary


class TestTaskSummary:
    def test_hours_minutes_seconds(self):
        assert task_summary("build", 3661) == "build: 1h 1m 1s"

    def test_minutes_only(self):
        assert task_summary("test", 120) == "test: 2m 0s"

    def test_zero(self):
        assert task_summary("noop", 0) == "noop: 0s"

    def test_seconds_only(self):
        assert task_summary("ping", 45) == "ping: 45s"

    def test_exact_hour(self):
        assert task_summary("job", 3600) == "job: 1h 0m 0s"


class TestStorageReport:
    def test_bytes(self):
        assert storage_report([("a.txt", 500)]) == ["a.txt: 500 B"]

    def test_kilobytes(self):
        assert storage_report([("b.bin", 2048)]) == ["b.bin: 2.0 KB"]

    def test_megabytes(self):
        result = storage_report([("c.dat", 1048576)])
        assert result == ["c.dat: 1.0 MB"]

    def test_multiple_files(self):
        result = storage_report([("x", 100), ("y", 2048)])
        assert len(result) == 2

    def test_gigabytes(self):
        result = storage_report([("big.iso", 1073741824)])
        assert result == ["big.iso: 1.0 GB"]


class TestTagLine:
    def test_single_tag(self):
        assert tag_line(["python"]) == "1 tag: python"

    def test_multiple_sorted(self):
        assert tag_line(["beta", "alpha"]) == "2 tags: alpha, beta"

    def test_duplicates_removed(self):
        assert tag_line(["a", "b", "a"]) == "2 tags: a, b"

    def test_empty(self):
        assert tag_line([]) == "0 tags: "

    def test_already_sorted(self):
        assert tag_line(["x", "y", "z"]) == "3 tags: x, y, z"
