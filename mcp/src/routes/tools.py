from typing import Any

from ..types import (
    GetCallersRequest,
    GetContextForChangeRequest,
    GetContractRequest,
    GetConventionsRequest,
    GetDependencyContextRequest,
    GetHistoryRequest,
)


def _tool_spec(name: str, description: str, input_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": input_schema,
    }


ALL_TOOLS: list[dict[str, Any]] = [
    _tool_spec(
        "get_context_for_change",
        "Retrieve ranked non-local context for an upcoming code change.",
        GetContextForChangeRequest.model_json_schema(),
    ),
    _tool_spec(
        "get_callers",
        "Return direct/transitive callers for a symbol.",
        GetCallersRequest.model_json_schema(),
    ),
    _tool_spec(
        "get_contract",
        "Return interface contract details for a symbol.",
        GetContractRequest.model_json_schema(),
    ),
    _tool_spec(
        "get_history",
        "Return relevant historical commits, PRs, and issues for a file/span.",
        GetHistoryRequest.model_json_schema(),
    ),
    _tool_spec(
        "get_conventions",
        "Return detected repository conventions and evidence.",
        GetConventionsRequest.model_json_schema(),
    ),
    _tool_spec(
        "get_dependency_context",
        "Return version-specific context for an external dependency API.",
        GetDependencyContextRequest.model_json_schema(),
    ),
]
