from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consumer_app.handlers import check_contact, check_server_config


class TestCheckServerConfig:
    def test_valid(self):
        assert check_server_config("192.168.1.1", 8080) == []

    def test_invalid_host(self):
        errors = check_server_config("999.0.0.1", 80)
        assert "invalid host: 999.0.0.1" in errors

    def test_invalid_port(self):
        errors = check_server_config("10.0.0.1", 99999)
        assert "invalid port: 99999" in errors

    def test_both_invalid(self):
        errors = check_server_config("bad", -1)
        assert len(errors) == 2

    def test_boundary_port_zero(self):
        assert check_server_config("0.0.0.0", 0) == []

    def test_boundary_port_max(self):
        assert check_server_config("255.255.255.255", 65535) == []


class TestCheckContact:
    def test_valid_email(self):
        assert check_contact("user@example.com") is True

    def test_no_at(self):
        assert check_contact("userexample.com") is False

    def test_empty_local(self):
        assert check_contact("@example.com") is False

    def test_empty_domain(self):
        assert check_contact("user@") is False

    def test_multiple_at(self):
        assert check_contact("a@b@c") is False
