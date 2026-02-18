"""Tool request/response schemas and enums for MCP endpoints."""

from enum import StrEnum

from pydantic import BaseModel, Field


class MissingContextType(StrEnum):
    """Normalized context-source categories returned by retrieval tools."""

    caller = "caller"
    contract = "contract"
    convention = "convention"
    rationale = "rationale"
    dependency = "dependency"
    mental_model = "mental_model"


class ConventionCategory(StrEnum):
    """Supported convention categories for repository guidance output."""

    structural = "structural"
    naming = "naming"
    error_handling = "error_handling"
    concurrency = "concurrency"
    security = "security"
    testing = "testing"


class DependencySourceType(StrEnum):
    """Evidence source types for dependency context records."""

    source_code = "source_code"
    docstring = "docstring"
    changelog = "changelog"
    migration_guide = "migration_guide"
    issue_thread = "issue_thread"
    example = "example"


class HistorySpan(BaseModel):
    """Line-range selector for scoped history lookups."""

    start_line: int = Field(..., ge=1)
    end_line: int = Field(..., ge=1)


class ToolContextItem(BaseModel):
    """Single contextual snippet returned for a change request."""

    source_type: MissingContextType
    location: str
    content: str
    relevance_score: float = Field(..., ge=0.0, le=1.0)
    explanation: str


class CallerEntry(BaseModel):
    """Caller location record for a symbol lookup."""

    file: str
    line: int = Field(..., ge=1)
    calling_function: str
    is_test: bool = False
    transitive: bool = False
    hop_count: int = Field(0, ge=0)


class ContractRecord(BaseModel):
    """Contract metadata associated with a symbol or callable target."""

    signature: str | None = None
    docstring: str | None = None
    preconditions: list[str] = Field(default_factory=list)
    postconditions: list[str] = Field(default_factory=list)
    invariants: list[str] = Field(default_factory=list)
    implicit_assumptions: list[str] = Field(default_factory=list)
    consumers_count: int = Field(0, ge=0)


class HistoryEntry(BaseModel):
    """Normalized repository history event used in tool responses."""

    commit_sha: str
    author: str
    timestamp: str
    message: str
    diff_summary: str | None = None
    linked_issues: list[str] = Field(default_factory=list)
    linked_prs: list[str] = Field(default_factory=list)
    rationale: str | None = None


class ConventionEntry(BaseModel):
    """Repository convention statement plus evidence and confidence."""

    description: str
    category: ConventionCategory
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
    codified_in: str | None = None


class DependencyContextRecord(BaseModel):
    """Dependency-related evidence item returned by context lookup."""

    source_type: DependencySourceType
    location: str
    content: str
    relevance: str


class GetContextForChangeRequest(BaseModel):
    """Input payload for top-level context retrieval."""

    file: str
    function: str | None = None
    task_description: str
    top_k: int = Field(10, ge=1, le=100)


class GetContextForChangeResponse(BaseModel):
    """Response payload for context retrieval with ranked items."""

    items: list[ToolContextItem] = Field(default_factory=list)


class GetCallersRequest(BaseModel):
    """Input payload for caller graph traversal."""

    symbol: str
    depth: int = Field(1, ge=1, le=10)


class GetCallersResponse(BaseModel):
    """Response payload containing caller records."""

    callers: list[CallerEntry] = Field(default_factory=list)


class GetContractRequest(BaseModel):
    """Input payload for contract lookup by symbol."""

    symbol: str


class GetContractResponse(BaseModel):
    """Response payload containing one contract record."""

    contract: ContractRecord


class GetHistoryRequest(BaseModel):
    """Input payload for repository history lookup."""

    file: str
    span: HistorySpan | None = None


class GetHistoryResponse(BaseModel):
    """Response payload containing normalized history entries."""

    entries: list[HistoryEntry] = Field(default_factory=list)


class GetConventionsRequest(BaseModel):
    """Input payload for repository conventions lookup."""

    category: ConventionCategory | None = None


class GetConventionsResponse(BaseModel):
    """Response payload containing matched convention entries."""

    conventions: list[ConventionEntry] = Field(default_factory=list)


class GetDependencyContextRequest(BaseModel):
    """Input payload for dependency context lookup."""

    package: str
    api: str | None = None


class GetDependencyContextResponse(BaseModel):
    """Response payload for dependency context and compatibility notes."""

    installed_version: str | None = None
    relevant_docs: list[DependencyContextRecord] = Field(default_factory=list)
    changelog_notes: list[str] = Field(default_factory=list)
    known_issues: list[str] = Field(default_factory=list)
    version_sensitivity: str | None = None
