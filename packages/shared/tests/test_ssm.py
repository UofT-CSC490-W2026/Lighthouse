from __future__ import annotations

import json
import types
from unittest.mock import MagicMock, patch

import pytest
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings

from shared import ssm


class ExampleSettings(BaseSettings):
    api_key: str = Field(alias="apiKey")
    aliases_only: str = Field(validation_alias=AliasChoices("first", "second"))
    tags: list[str]


@pytest.mark.unit
def test_dedupe_and_field_keys():
    field = ExampleSettings.model_fields["aliases_only"]

    assert ssm._dedupe(["a", "", "a", "b"]) == ["a", "b"]
    assert ssm._field_keys("aliases_only", field) == ["first", "second", "aliases_only"]


@pytest.mark.unit
def test_get_ssm_client_import_error():
    ssm.get_ssm_client.cache_clear()
    original_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "boto3":
            raise ImportError("missing boto3")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        with pytest.raises(RuntimeError, match="boto3 must be installed"):
            ssm.get_ssm_client("ca-central-1")


@pytest.mark.unit
def test_get_ssm_client_uses_region():
    ssm.get_ssm_client.cache_clear()
    boto3 = types.SimpleNamespace(client=MagicMock(return_value="client"))

    with patch.dict("sys.modules", {"boto3": boto3}):
        assert ssm.get_ssm_client("ca-central-1") == "client"

    boto3.client.assert_called_once_with("ssm", region_name="ca-central-1")


@pytest.mark.unit
def test_get_parameter_value_success_and_non_string():
    ssm._get_parameter_value.cache_clear()
    ssm.get_ssm_client.cache_clear()
    fake_exceptions = types.SimpleNamespace(BotoCoreError=Exception, ClientError=Exception)

    with patch.dict("sys.modules", {"botocore.exceptions": fake_exceptions}):
        with patch.object(
            ssm,
            "get_ssm_client",
            return_value=MagicMock(
                get_parameter=MagicMock(
                    return_value={"Parameter": {"Value": "payload"}}
                )
            ),
        ):
            assert ssm._get_parameter_value("settings") == "payload"

        ssm._get_parameter_value.cache_clear()
        with patch.object(
            ssm,
            "get_ssm_client",
            return_value=MagicMock(
                get_parameter=MagicMock(return_value={"Parameter": {"Value": 123}})
            ),
        ):
            with pytest.raises(RuntimeError, match="contain a string value"):
                ssm._get_parameter_value("settings")


@pytest.mark.unit
def test_get_parameter_value_wraps_client_errors():
    class FakeClientError(Exception):
        pass

    fake_exceptions = types.SimpleNamespace(
        BotoCoreError=RuntimeError,
        ClientError=FakeClientError,
    )
    ssm._get_parameter_value.cache_clear()

    with patch.dict("sys.modules", {"botocore.exceptions": fake_exceptions}):
        with patch.object(
            ssm,
            "get_ssm_client",
            return_value=MagicMock(
                get_parameter=MagicMock(side_effect=FakeClientError("boom"))
            ),
        ):
            with pytest.raises(RuntimeError, match="Failed to load settings"):
                ssm._get_parameter_value("settings")


@pytest.mark.unit
def test_get_parameter_value_botocore_import_error():
    ssm._get_parameter_value.cache_clear()
    original_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "botocore.exceptions":
            raise ImportError("missing botocore")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        with pytest.raises(RuntimeError, match="botocore is required"):
            ssm._get_parameter_value("settings")


@pytest.mark.unit
def test_get_region_name_prefers_aws_region(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "ca-central-1")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

    assert ssm._get_region_name() == "ca-central-1"


@pytest.mark.unit
def test_load_parameter_payload_errors():
    with patch.object(ssm, "_get_parameter_value", return_value="not-json"):
        with pytest.raises(RuntimeError, match="must contain a JSON object"):
            ssm._load_parameter_payload("settings")

    with patch.object(ssm, "_get_parameter_value", return_value=json.dumps(["x"])):
        with pytest.raises(RuntimeError, match="must decode to a JSON object"):
            ssm._load_parameter_payload("settings")

    with patch.object(ssm, "_get_parameter_value", return_value=json.dumps({"ok": True})):
        assert ssm._load_parameter_payload("settings") == {"ok": True}


@pytest.mark.unit
def test_ssm_settings_source_returns_empty_without_env(monkeypatch):
    monkeypatch.delenv("LIGHTHOUSE_SSM", raising=False)

    source = ssm.SSMSettingsSource(ExampleSettings, "LIGHTHOUSE_SSM")

    assert source() == {}
    assert source.get_field_value(ExampleSettings.model_fields["api_key"], "api_key") == (
        None,
        "api_key",
        False,
    )


@pytest.mark.unit
def test_ssm_settings_source_maps_aliases_and_complex_values(monkeypatch):
    monkeypatch.setenv("LIGHTHOUSE_SSM", "settings")
    payload = {
        "apiKey": "secret",
        "second": "fallback",
        "tags": "[\"a\", \"b\"]",
    }

    with patch.object(ssm, "_load_parameter_payload", return_value=payload):
        source = ssm.SSMSettingsSource(ExampleSettings, "LIGHTHOUSE_SSM")
        assert source() == {
            "api_key": "secret",
            "aliases_only": "fallback",
            "tags": ["a", "b"],
        }


@pytest.mark.unit
def test_ssm_settings_sources_appends_ssm_source():
    init_settings = MagicMock()
    env_settings = MagicMock()
    dotenv_settings = MagicMock()
    file_secret_settings = MagicMock()

    sources = ssm.ssm_settings_sources(
        "LIGHTHOUSE_SSM",
        ExampleSettings,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    )

    assert sources[:4] == (
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    )
    assert isinstance(sources[4], ssm.SSMSettingsSource)
