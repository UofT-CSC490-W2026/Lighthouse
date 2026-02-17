from enum import StrEnum

from pydantic import BaseModel, Field


class MissingContextType(StrEnum):
    caller = "caller"
    contract = "contract"
    convention = "convention"
    rationale = "rationale"
    dependency = "dependency"
    mental_model = "mental_model"


class ConventionCategory(StrEnum):
    structural = "structural"
    naming = "naming"
    error_handling = "error_handling"
    concurrency = "concurrency"
    security = "security"
    testing = "testing"


class DependencySourceType(StrEnum):
    source_code = "source_code"
    docstring = "docstring"
    changelog = "changelog"
    migration_guide = "migration_guide"
    issue_thread = "issue_thread"
    example = "example"


class HistorySpan(BaseModel):
    start_line: int = Field(..., ge=1)
    end_line: int = Field(..., ge=1)


class ToolContextItem(BaseModel):
    source_type: MissingContextType
    location: str
    content: str
    relevance_score: float = Field(..., ge=0.0, le=1.0)
    explanation: str


class CallerEntry(BaseModel):
    file: str
    line: int = Field(..., ge=1)
    calling_function: str
    is_test: bool = False
    transitive: bool = False
    hop_count: int = Field(0, ge=0)


class ContractRecord(BaseModel):
    signature: str | None = None
    docstring: str | None = None
    preconditions: list[str] = Field(default_factory=list)
    postconditions: list[str] = Field(default_factory=list)
    invariants: list[str] = Field(default_factory=list)
    implicit_assumptions: list[str] = Field(default_factory=list)
    consumers_count: int = Field(0, ge=0)


class HistoryEntry(BaseModel):
    commit_sha: str
    author: str
    timestamp: str
    message: str
    diff_summary: str | None = None
    linked_issues: list[str] = Field(default_factory=list)
    linked_prs: list[str] = Field(default_factory=list)
    rationale: str | None = None


class ConventionEntry(BaseModel):
    description: str
    category: ConventionCategory
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
    codified_in: str | None = None


class DependencyContextRecord(BaseModel):
    source_type: DependencySourceType
    location: str
    content: str
    relevance: str


class GetContextForChangeRequest(BaseModel):
    file: str
    function: str | None = None
    task_description: str
    top_k: int = Field(10, ge=1, le=100)


class GetContextForChangeResponse(BaseModel):
    items: list[ToolContextItem] = Field(default_factory=list)


class GetCallersRequest(BaseModel):
    symbol: str
    depth: int = Field(1, ge=1, le=10)


class GetCallersResponse(BaseModel):
    callers: list[CallerEntry] = Field(default_factory=list)


class GetContractRequest(BaseModel):
    symbol: str


class GetContractResponse(BaseModel):
    contract: ContractRecord


class GetHistoryRequest(BaseModel):
    file: str
    span: HistorySpan | None = None


class GetHistoryResponse(BaseModel):
    entries: list[HistoryEntry] = Field(default_factory=list)


class GetConventionsRequest(BaseModel):
    category: ConventionCategory | None = None


class GetConventionsResponse(BaseModel):
    conventions: list[ConventionEntry] = Field(default_factory=list)


class GetDependencyContextRequest(BaseModel):
    package: str
    api: str | None = None


class GetDependencyContextResponse(BaseModel):
    installed_version: str | None = None
    relevant_docs: list[DependencyContextRecord] = Field(default_factory=list)
    changelog_notes: list[str] = Field(default_factory=list)
    known_issues: list[str] = Field(default_factory=list)
    version_sensitivity: str | None = None
