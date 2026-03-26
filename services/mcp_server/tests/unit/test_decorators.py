import pytest

from mcp_server.utilities.decorators import (
    httproute,
    toolcall,
    collect_routables,
    collect_toolcalls,
    params_to_model,
    RouteMeta,
    ToolCallMeta,
)


@pytest.mark.unit
class TestHttpRoute:
    def test_httproute_stamps_metadata(self):
        @httproute("GET", "/path", name="test_route", description="desc")
        def handler():
            pass

        meta = handler.__httproute__
        assert isinstance(meta, RouteMeta)
        assert meta.method == "GET"
        assert meta.path == "/path"
        assert meta.name == "test_route"
        assert meta.description == "desc"

    def test_httproute_defaults(self):
        @httproute("POST", "/other")
        def handler():
            pass

        meta = handler.__httproute__
        assert meta.auth_required is True
        assert meta.name == ""
        assert meta.description == ""


@pytest.mark.unit
class TestToolCall:
    def test_toolcall_stamps_metadata(self):
        @toolcall("name", description="desc")
        def handler():
            pass

        meta = handler.__toolcall__
        assert isinstance(meta, ToolCallMeta)
        assert meta.name == "name"
        assert meta.description == "desc"
        assert meta.auth_required is True

    def test_toolcall_auth_not_required(self):
        @toolcall("name", auth_required=False)
        def handler():
            pass

        assert handler.__toolcall__.auth_required is False


@pytest.mark.unit
class TestCollectors:
    def test_collect_routables(self):
        class FakeEngine:
            @httproute("GET", "/foo", name="foo")
            def foo(self):
                pass

            @httproute("POST", "/bar", name="bar")
            def bar(self):
                pass

        obj = FakeEngine()
        routes = collect_routables(obj)
        assert "GET /foo" in routes
        assert "POST /bar" in routes
        assert len(routes) == 2

    def test_collect_toolcalls(self):
        class FakeEngine:
            @toolcall("do_thing", description="does a thing")
            def do_thing(self):
                pass

        obj = FakeEngine()
        tools = collect_toolcalls(obj)
        assert "do_thing" in tools
        assert tools["do_thing"].meta.description == "does a thing"
        assert tools["do_thing"].owner is obj


@pytest.mark.unit
class TestParamsToModel:
    def test_params_to_model_basic(self):
        def my_func(name: str, age: int):
            pass

        Model = params_to_model(my_func)
        assert "name" in Model.model_fields
        assert "age" in Model.model_fields
        assert Model.__name__ == "MyFuncInput"

    def test_params_to_model_with_defaults(self):
        def my_func(name: str, count: int = 10):
            pass

        Model = params_to_model(my_func)
        instance = Model(name="test")
        assert instance.count == 10

    def test_params_to_model_skips_self(self):
        class Dummy:
            def method(self, query: str):
                pass

        Model = params_to_model(Dummy.method)
        assert "self" not in Model.model_fields
        assert "query" in Model.model_fields
