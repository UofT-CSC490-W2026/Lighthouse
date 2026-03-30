from __future__ import annotations

import os


_AWS_PROFILE_KEYS = ("AWS_PROFILE", "AWS_DEFAULT_PROFILE")
_AWS_CREDENTIAL_KEYS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")


def prefer_explicit_aws_credentials() -> None:
    """Prefer direct AWS credential env vars over profile-based resolution.

    In containerized local development we often inject ``AWS_ACCESS_KEY_ID`` and
    ``AWS_SECRET_ACCESS_KEY`` directly, but a stray ``AWS_PROFILE`` from a local
    ``.env`` file can still cause botocore to fail before it considers those
    credentials. When key material is present, drop the profile selectors so
    boto3 resolves credentials from the environment instead.
    """
    if not all(os.getenv(key, "").strip() for key in _AWS_CREDENTIAL_KEYS):
        return

    for key in _AWS_PROFILE_KEYS:
        os.environ.pop(key, None)
