from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consumer_app.pipelines import api_endpoint, camel_keys, export_row


class TestApiEndpoint:
    def test_basic(self):
        assert api_endpoint("example.com", 2, "users") == "https://example.com/api/v2/users"

    def test_version_1(self):
        assert api_endpoint("host.io", 1, "items") == "https://host.io/api/v1/items"

    def test_nested_resource(self):
        result = api_endpoint("a.com", 3, "data/export")
        assert result == "https://a.com/api/v3/data/export"


class TestExportRow:
    def test_flat_dict(self):
        assert export_row({"a": 1, "b": 2}) == "1,2"

    def test_nested_dict(self):
        result = export_row({"x": {"y": 10}})
        assert result == "10"

    def test_mixed(self):
        result = export_row({"name": "alice", "meta": {"age": 30}})
        assert result == "alice,30"

    def test_value_with_comma(self):
        result = export_row({"note": "a,b"})
        assert result == '"a,b"'


class TestCamelKeys:
    def test_single_word(self):
        assert camel_keys({"name": 1}) == {"name": 1}

    def test_snake_case(self):
        assert camel_keys({"first_name": "A", "last_name": "B"}) == {
            "firstName": "A",
            "lastName": "B",
        }

    def test_empty(self):
        assert camel_keys({}) == {}

    def test_multi_segment(self):
        assert camel_keys({"my_long_key": 42}) == {"myLongKey": 42}
