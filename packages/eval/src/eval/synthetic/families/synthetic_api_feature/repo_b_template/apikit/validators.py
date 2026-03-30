from __future__ import annotations


def validate_email(email: str) -> bool:
    parts = email.split("@")
    if len(parts) != 2:
        return False
    local, domain = parts
    return bool(local) and bool(domain)


def validate_port(port: int) -> bool:
    return 0 <= port <= 65535


def validate_ip_v4(ip: str) -> bool:
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        try:
            num = int(part)
        except ValueError:
            return False
        if num < 0 or num > 255:
            return False
    return True
