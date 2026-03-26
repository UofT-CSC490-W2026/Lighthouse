"""AWS SSM Parameter Store settings source for Pydantic BaseSettings.

Provides SSMSettingsSource and a convenience function so any service can
load configuration from a single encrypted JSON blob in SSM.  When the
designated environment variable is not set, the source returns an empty
dict and behaviour is identical to plain env-var / .env loading.

boto3 is imported lazily so it only needs to be installed in services
that actually enable SSM.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

from pydantic import AliasChoices
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource


def _dedupe(values: list[str]) -> list[str]:
    """Return *values* without empty entries or duplicates, preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _field_keys(field_name: str, field: FieldInfo) -> list[str]:
    """Collect the possible payload keys for a settings field."""
    keys = [field_name]

    alias = field.validation_alias
    if isinstance(alias, str):
        keys.insert(0, alias)
    elif isinstance(alias, AliasChoices):
        keys = [choice for choice in alias.choices if isinstance(choice, str)] + keys

    if isinstance(field.alias, str):
        keys.insert(0, field.alias)

    return _dedupe(keys)


@lru_cache(maxsize=None)
def get_ssm_client(region_name: str | None = None) -> Any:
    """Create and cache an SSM client for the configured AWS region."""
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError(
            "boto3 must be installed to load settings from AWS SSM Parameter Store."
        ) from exc

    kwargs: dict[str, Any] = {}
    if region_name:
        kwargs["region_name"] = region_name
    return boto3.client("ssm", **kwargs)


@lru_cache(maxsize=None)
def _get_parameter_value(parameter_name: str, region_name: str | None = None) -> str:
    """Fetch and decrypt a raw settings payload from SSM."""
    try:
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError as exc:
        raise RuntimeError(
            "botocore is required to load settings from AWS SSM Parameter Store."
        ) from exc

    try:
        response = get_ssm_client(region_name).get_parameter(
            Name=parameter_name,
            WithDecryption=True,
        )
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError(
            f"Failed to load settings from SSM parameter {parameter_name!r}."
        ) from exc

    value = response["Parameter"]["Value"]
    if not isinstance(value, str):
        raise RuntimeError(
            f"Expected SSM parameter {parameter_name!r} to contain a string value."
        )
    return value


def _get_region_name() -> str | None:
    """Resolve the AWS region from the process environment."""
    for key in ("AWS_REGION", "AWS_DEFAULT_REGION"):
        value = os.getenv(key, "").strip()
        if value:
            return value
    return None


def _load_parameter_payload(
    parameter_name: str,
    region_name: str | None = None,
) -> dict[str, Any]:
    """Decode the SSM settings payload as a JSON object."""
    raw_value = _get_parameter_value(parameter_name, region_name)
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"SSM parameter {parameter_name!r} must contain a JSON object."
        ) from exc

    if not isinstance(payload, dict):
        raise RuntimeError(
            f"SSM parameter {parameter_name!r} must decode to a JSON object."
        )
    return payload


class SSMSettingsSource(PydanticBaseSettingsSource):
    """Load settings defaults from a single JSON blob stored in AWS SSM.

    The *ssm_env_var* argument names the environment variable that holds the
    SSM parameter name.  If that variable is empty or unset, the source
    returns an empty dict (no-op for local development).
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        ssm_env_var: str,
    ) -> None:
        super().__init__(settings_cls)
        self._ssm_env_var = ssm_env_var

    def get_field_value(
        self,
        field: FieldInfo,
        field_name: str,
    ) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        parameter_name = os.getenv(self._ssm_env_var, "").strip()
        if not parameter_name:
            return {}

        payload = _load_parameter_payload(parameter_name, _get_region_name())
        data: dict[str, Any] = {}

        for field_name, field in self.settings_cls.model_fields.items():
            for key in _field_keys(field_name, field):
                if key not in payload:
                    continue

                value = payload[key]
                if isinstance(value, str) and self.field_is_complex(field):
                    value = self.prepare_field_value(field_name, field, value, True)

                data[field_name] = value
                break

        return data


def ssm_settings_sources(
    ssm_env_var: str,
    settings_cls: type[BaseSettings],
    init_settings: PydanticBaseSettingsSource,
    env_settings: PydanticBaseSettingsSource,
    dotenv_settings: PydanticBaseSettingsSource,
    file_secret_settings: PydanticBaseSettingsSource,
) -> tuple[PydanticBaseSettingsSource, ...]:
    """Standard source ordering: init > env > dotenv > file_secret > SSM."""
    return (
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
        SSMSettingsSource(settings_cls, ssm_env_var),
    )
