from __future__ import annotations

from apikit.validators import validate_email, validate_ip_v4, validate_port


def check_server_config(host: str, port: int) -> list[str]:
    errors: list[str] = []
    if not validate_ip_v4(host):
        errors.append(f"invalid host: {host}")
    if not validate_port(port):
        errors.append(f"invalid port: {port}")
    return errors


def check_contact(email: str) -> bool:
    return validate_email(email)
