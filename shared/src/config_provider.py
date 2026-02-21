"""Runtime configuration bootstrap with optional AWS Parameter Store loading."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

LOGGER = logging.getLogger(__name__)

_LOCAL_APP_ENVS = {"local", "dev", "development", "test"}
_DEFAULT_CONFIG_PROVIDER = "auto"
_DEFAULT_PARAMETER_PREFIX = "/lighthouse/{app_env}/{service}"


@dataclass(frozen=True, slots=True)
class ConfigBootstrapResult:
    """Summary of runtime config bootstrap behavior for a service process."""

    service: str
    app_env: str
    provider: str
    parameter_prefix: str | None
    parameters_loaded: int


def bootstrap_runtime_config(service: str) -> ConfigBootstrapResult:
    """Bootstrap environment variables from configured runtime provider policy."""
    app_env = _resolve_app_env()
    provider = _resolve_config_provider()

    if not _should_load_parameter_store(provider=provider, app_env=app_env):
        return ConfigBootstrapResult(
            service=service,
            app_env=app_env,
            provider=provider,
            parameter_prefix=None,
            parameters_loaded=0,
        )

    parameter_prefix = _resolve_parameter_prefix(service=service, app_env=app_env)
    parameters_loaded = _load_parameters_from_ssm(parameter_prefix=parameter_prefix)

    return ConfigBootstrapResult(
        service=service,
        app_env=app_env,
        provider=provider,
        parameter_prefix=parameter_prefix,
        parameters_loaded=parameters_loaded,
    )


def _resolve_app_env() -> str:
    """Resolve normalized application environment name from process env."""
    return (os.getenv("APP_ENV", "local").strip().lower()) or "local"


def _resolve_config_provider() -> str:
    """Resolve config provider mode (`auto`, `env`, or `ssm`)."""
    provider = (
        os.getenv("LIGHTHOUSE_CONFIG_PROVIDER", _DEFAULT_CONFIG_PROVIDER)
        .strip()
        .lower()
    )
    if provider in {"auto", "env", "ssm"}:
        return provider
    LOGGER.warning(
        "Unknown LIGHTHOUSE_CONFIG_PROVIDER '%s'; defaulting to '%s'",
        provider,
        _DEFAULT_CONFIG_PROVIDER,
    )
    return _DEFAULT_CONFIG_PROVIDER


def _should_load_parameter_store(*, provider: str, app_env: str) -> bool:
    """Determine if Parameter Store should be queried for this runtime."""
    if provider == "ssm":
        return True
    if provider == "env":
        return False
    return app_env not in _LOCAL_APP_ENVS


def _resolve_parameter_prefix(*, service: str, app_env: str) -> str:
    """Resolve the SSM path prefix used for parameter lookup."""
    service_key = re.sub(r"[^A-Za-z0-9]+", "_", service).upper()
    service_override = os.getenv(f"LIGHTHOUSE_PARAMETER_PREFIX_{service_key}")
    template = (
        service_override
        or os.getenv("LIGHTHOUSE_PARAMETER_PREFIX")
        or _DEFAULT_PARAMETER_PREFIX
    )
    try:
        rendered = template.format(app_env=app_env, service=service)
    except KeyError:
        rendered = template
    rendered = rendered.strip()
    if not rendered:
        rendered = _DEFAULT_PARAMETER_PREFIX.format(app_env=app_env, service=service)
    return "/" + rendered.strip("/")


def _load_parameters_from_ssm(*, parameter_prefix: str) -> int:
    """Load parameters from AWS SSM and populate missing environment variables."""
    try:
        import boto3
    except ModuleNotFoundError:
        LOGGER.warning(
            "boto3 is not installed; skipping AWS Parameter Store bootstrap for prefix '%s'",
            parameter_prefix,
        )
        return 0

    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"

    try:
        client = boto3.client("ssm", region_name=region)
        next_token: str | None = None
        loaded = 0

        while True:
            request = {
                "Path": parameter_prefix,
                "Recursive": True,
                "WithDecryption": True,
            }
            if next_token:
                request["NextToken"] = next_token

            response = client.get_parameters_by_path(**request)
            for parameter in response.get("Parameters", []):
                env_name = _parameter_name_to_env_name(
                    parameter_name=parameter.get("Name", ""),
                    parameter_prefix=parameter_prefix,
                )
                if not env_name:
                    continue
                if env_name in os.environ:
                    continue
                os.environ[env_name] = parameter.get("Value", "")
                loaded += 1

            next_token = response.get("NextToken")
            if not next_token:
                break

        return loaded
    except Exception as exc:
        LOGGER.warning(
            "Failed to load AWS Parameter Store values from '%s': %s",
            parameter_prefix,
            exc,
        )
        return 0


def _parameter_name_to_env_name(
    *, parameter_name: str, parameter_prefix: str
) -> str | None:
    """Convert a full SSM parameter path into an uppercase env-var key."""
    name = (parameter_name or "").strip()
    prefix = parameter_prefix.rstrip("/")
    if not name:
        return None
    if name.startswith(prefix):
        name = name[len(prefix) :]
    name = name.strip("/")
    if not name:
        return None
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()
    return normalized or None
