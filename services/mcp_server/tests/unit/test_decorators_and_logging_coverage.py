from __future__ import annotations

from types import SimpleNamespace

import pytest

from mcp_server.utilities.decorators import collect_routables, collect_toolcalls, params_to_model, routable
from mcp_server.utilities.logging import LogFormatter, get_logger, pp, timed


class BrokenLookup:
    @property
    def broken(self):
        raise AttributeError("nope")


@pytest.mark.unit
def test_routable_alias_and_collectors_handle_attribute_errors():
    class Routed:
        @routable("get", "/alias", name="alias")
        def alias(self):
            return None

    routes = collect_routables(Routed(), BrokenLookup())
    assert "GET /alias" in routes
    assert collect_toolcalls(BrokenLookup()) == {}


@pytest.mark.unit
def test_params_to_model_handles_forward_refs_and_missing_annotations():
    def missing_types(value: "MissingType", plain):
        return None

    model = params_to_model(missing_types)
    assert "MissingType" in str(model.model_fields["value"].annotation)
    assert str(model.model_fields["plain"].annotation) == "typing.Any"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_logging_helpers_cover_timed_and_pp(capsys):
    logger = get_logger("coverage.logger")
    formatter = LogFormatter()
    record = logger.makeRecord("coverage.logger", 999, __file__, 1, "msg", (), None)
    assert "msg" in formatter.format(record)

    owner = SimpleNamespace(log=logger)

    @timed
    async def work(self, value):
        return value + 1

    assert await work(owner, 1) == 2

    pp("hello", end="!")
    out = capsys.readouterr().out
    assert "hello" in out
    assert out.endswith("!")
