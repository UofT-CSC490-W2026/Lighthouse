from __future__ import annotations

import os

import pytest

from shared.aws import prefer_explicit_aws_credentials


@pytest.mark.unit
def test_prefer_explicit_aws_credentials_removes_profile_env(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-access-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret-key")
    monkeypatch.setenv("AWS_PROFILE", "490")
    monkeypatch.setenv("AWS_DEFAULT_PROFILE", "default")

    prefer_explicit_aws_credentials()

    assert "AWS_PROFILE" not in os.environ
    assert "AWS_DEFAULT_PROFILE" not in os.environ


@pytest.mark.unit
def test_prefer_explicit_aws_credentials_keeps_profile_without_static_keys(monkeypatch):
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.setenv("AWS_PROFILE", "490")

    prefer_explicit_aws_credentials()

    assert os.environ["AWS_PROFILE"] == "490"
