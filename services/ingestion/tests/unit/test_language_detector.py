from __future__ import annotations

import pytest

from ingestion.language.detector import ExtensionLanguageDetector


@pytest.mark.unit
class TestExtensionLanguageDetector:
    """Tests for ExtensionLanguageDetector."""

    def setup_method(self) -> None:
        self.detector = ExtensionLanguageDetector()

    def test_python(self) -> None:
        assert self.detector.detect("src/main.py") == "python"

    def test_javascript(self) -> None:
        assert self.detector.detect("app.js") == "javascript"

    def test_typescript(self) -> None:
        assert self.detector.detect("app.ts") == "typescript"

    def test_tsx(self) -> None:
        assert self.detector.detect("Component.tsx") == "typescript"

    def test_jsx(self) -> None:
        assert self.detector.detect("Component.jsx") == "javascript"

    def test_go(self) -> None:
        assert self.detector.detect("main.go") == "go"

    def test_rust(self) -> None:
        assert self.detector.detect("lib.rs") == "rust"

    def test_java(self) -> None:
        assert self.detector.detect("Main.java") == "java"

    def test_dockerfile(self) -> None:
        assert self.detector.detect("Dockerfile") == "dockerfile"

    def test_makefile(self) -> None:
        assert self.detector.detect("Makefile") == "makefile"

    def test_dockerfile_in_subdir(self) -> None:
        assert self.detector.detect("docker/Dockerfile") == "dockerfile"

    def test_unknown_extension(self) -> None:
        assert self.detector.detect("data.xyz") is None

    def test_no_extension(self) -> None:
        assert self.detector.detect("README") is None

    def test_shell(self) -> None:
        assert self.detector.detect("deploy.sh") == "shell"

    def test_yaml(self) -> None:
        assert self.detector.detect("config.yaml") == "yaml"

    def test_yml(self) -> None:
        assert self.detector.detect("config.yml") == "yaml"

    def test_json(self) -> None:
        assert self.detector.detect("package.json") == "json"

    def test_toml(self) -> None:
        assert self.detector.detect("pyproject.toml") == "toml"
