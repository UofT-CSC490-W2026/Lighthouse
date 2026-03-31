from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consumer_app.handlers import check_contact, check_server_config
from consumer_app.pipelines import api_endpoint, camel_keys, export_row
from consumer_app.reports import storage_report, tag_line, task_summary


def test_task_011_api_endpoint_https() -> None:
    assert api_endpoint('example.com', 3, 'users') == 'https://example.com/api/v3/users'

def test_task_012_api_endpoint_version_prefix() -> None:
    assert api_endpoint('h.io', 2, 'items') == 'https://h.io/api/v2/items'

def test_task_013_export_row_uses_flatten() -> None:
    assert export_row({'outer': {'x': 7}}) == '7'

def test_task_014_export_row_preserve_order() -> None:
    assert export_row({'b': 2, 'a': 1}) == '2,1'

def test_task_015_camel_keys_transforms_snake_case() -> None:
    assert camel_keys({'first_name': 'Ada'}) == {'firstName': 'Ada'}

def test_task_016_camel_keys_lowercase_first_segment() -> None:
    assert camel_keys({'user_id': 1}) == {'userId': 1}

def test_task_017_check_server_config_valid_host() -> None:
    assert check_server_config('10.0.0.1', 8080) == []

def test_task_018_check_server_config_invalid_port() -> None:
    assert 'invalid port: 70000' in check_server_config('10.0.0.1', 70000)

def test_task_019_check_contact_truthiness() -> None:
    assert check_contact('user@example.com') is True

def test_task_020_check_contact_invalid_email() -> None:
    assert check_contact('bad-email') is False

def test_task_021_task_summary_uses_formatter() -> None:
    assert task_summary('build', 3661) == 'build: 1h 1m 1s'

def test_task_022_task_summary_prefix_format() -> None:
    assert task_summary('job', 60) == 'job: 1m 0s'

def test_task_023_storage_report_human_units() -> None:
    assert storage_report([('blob.bin', 2048)]) == ['blob.bin: 2.0 KB']

def test_task_024_storage_report_spacing() -> None:
    assert storage_report([('f.txt', 500)]) == ['f.txt: 500 B']

def test_task_025_tag_line_deduplicates() -> None:
    assert tag_line(['a', 'b', 'a']) == '2 tags: a, b'

def test_task_026_tag_line_singular_plural() -> None:
    assert tag_line(['python']) == '1 tag: python'

def test_task_027_tag_line_separator() -> None:
    assert tag_line(['x', 'y']) == '2 tags: x, y'

def test_task_028_api_endpoint_leading_slash() -> None:
    assert api_endpoint('svc.local', 1, 'status') == 'https://svc.local/api/v1/status'

def test_task_029_export_row_values_not_keys() -> None:
    assert export_row({'name': 'alice', 'age': 30}) == 'alice,30'

def test_task_030_check_server_config_host_message() -> None:
    assert 'invalid host: bad-host' in check_server_config('bad-host', 80)

