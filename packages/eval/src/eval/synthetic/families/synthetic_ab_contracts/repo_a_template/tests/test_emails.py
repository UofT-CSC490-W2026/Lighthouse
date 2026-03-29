from __future__ import annotations

from consumer_app.emails import primary_contact


def test_primary_contact_uses_provider_email_cleanup() -> None:
    emails = ["  TEAM@Example.com  ", "backup@example.com"]
    assert primary_contact(emails) == "team@example.com"
