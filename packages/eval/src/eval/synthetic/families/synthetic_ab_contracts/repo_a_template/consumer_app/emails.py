from __future__ import annotations

from providerlib.identity import choose_primary_email


def primary_contact(emails: list[str]) -> str:
    return choose_primary_email(emails)
