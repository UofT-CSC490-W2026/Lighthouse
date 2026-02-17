# MCP Context Service: Datasets 

## Goal and framing

Build a cloud-deployed MCP service that reduces coding-agent failure from missing non-local context (dependencies, adjacent services, design rationale, historical fixes).

Two primary outcomes matter:
1. Better task success and lower regression risk.
2. Measurable reliability gains under reproducible benchmarks.

## Ideal Datasets

Our goal is to improve the efficacy of AI coding agents, which may produce incorrect changes because they lack relevant context that exists outside their immediate working scope. To build and evaluate systems that surface this missing context, the ideal dataset would consist of tuples pairing a coding task with a point-in-time snapshot of the full software environment: the target repository, but its transitive dependencies, documentation, and version history along with a gold label identifying the precise, minimal set of non-local information an agent would have needed to produce a correct change. This label is the core artifact: it answers the question *"what did the agent need to know, but didn't, in order to get this right?"* and it spans multiple axes of context, including interface contracts and type signatures across module and library boundaries, downstream callers and invariants that a local change might violate, architectural conventions and design rationale recoverable from project history, and relevant documentation or specifications from external dependencies.

Each entry would additionally include a failed agent attempt (produced without sufficient context), the corresponding corrected code (produced by a human or by an agent given adequate context), and the failure signal linking the two such as a test failure, type error, or behavioural regression. The causal structure of this data is what makes it powerful: the delta between the failed and successful attempts is attributable to the presence or absence of the labeled context. With such a dataset, one could train and evaluate any retrieval or reasoning approach against a ground-truth definition of what "the right context" is for a given task, and measure whether surfacing it actually changes agent outcomes.

### Aspirational Dataset Schemas

#### Dataset 1: Context-Attributed Agent Failures

The central dataset. Each row captures a coding task where an agent failed, the corrected outcome, and a precise attribution of what non-local context was missing.

```
{
  repo:                 str,              # target repository
  repo_snapshot:        commit_sha,       # frozen state of repo at task time
  dependency_snapshot:  [package@version], # pinned versions of all transitive dependencies
  task:                 str,              # natural language description of the coding task
  agent_attempt: {
    diff:               Diff,             # the incorrect change
    files_viewed:       [str],            # what the agent looked at
    searches_performed: [str],            # queries the agent issued
  },
  failure_signal: {
    type:               enum[test_failure, type_error, runtime_error, semantic_bug, convention_violation],
    message:            str,
    affected_locations: [{file, line}],   # where the failure manifested
  },
  corrected_diff:       Diff,             # the correct change
  missing_context: [{
    source:             enum[same_repo, dependency, documentation, history],
    file:               str,              # file path (or doc URL, or commit sha)
    span:               (start_line, end_line),
    content:            str,
    context_type:       enum[contract, caller, type_def, invariant, convention, rationale, config, doc],
    explanation:        str,              # why this context was necessary for correctness
  }],
}
```

#### Dataset 2: Interface Contracts and Cross-Boundary Specifications

Each row describes a function or module boundary, its (possibly implicit) contract, and the set of callers/consumers that depend on that contract — across repo and library boundaries.

```
{
  repo:                 str,
  function:             fully_qualified_name,
  defined_in:           {file, span},
  contract: {
    signature:          str,              # type signature or prototype
    preconditions:      [str],            # e.g. "input list must be non-empty"
    postconditions:     [str],            # e.g. "returns a value in [0, 1]"
    invariants:         [str],            # e.g. "does not mutate input"
    implicit:           [str],            # unwritten assumptions recoverable from tests/usage
    source_of_truth:    enum[type_system, docstring, test_assertion, usage_pattern, unwritten],
  },
  consumers: [{
    location:           {repo, file, span},
    assumption_relied_on: str,            # which part of the contract this caller depends on
  }],
  known_violations: [{
    diff:               Diff,
    which_contract_broken: str,
    failure_mode:       str,
  }],
}
```

#### Dataset 3: Downstream Impact Chains

Each row captures a local change and the full causal chain through which it produces a failure at a distant location — the longer the chain, the more valuable the example.

```
{
  repo:                 str,
  repo_snapshot:        commit_sha,
  local_change:         Diff,             # the triggering modification
  change_location:      {file, function},
  failure_location:     {file, function, test},  # where the breakage surfaced
  causal_chain: [{                        # ordered sequence from change to failure
    node:               {file, function},
    relationship:       enum[calls, inherits, imports, configures, instantiates, overrides],
    what_propagates:    str,              # e.g. "changed return type", "altered side effect"
  }],
  chain_length:         int,              # number of hops between change and failure
  minimal_context:      [{file, span}],   # smallest set of intermediate nodes needed to foresee the failure
}
```

#### Dataset 4: Architectural Conventions and Project Norms

Each row encodes an implicit or explicit convention in a codebase, examples of code that follow it, and examples of agent-generated code that violates it.

```
{
  repo:                 str,
  convention: {
    description:        str,              # e.g. "all DB access goes through the repository layer"
    category:           enum[structural, naming, error_handling, concurrency, security, testing, other],
    evidence: [{                          # locations that establish the pattern
      file:             str,
      span:             (start_line, end_line),
    }],
    codified_in:        str | null,       # lint rule, ADR, style guide, or null if purely implicit
  },
  conforming_examples:  [{file, span}],   # code that correctly follows the convention
  violations: [{
    diff:               Diff,             # agent-generated code that breaks the convention
    what_was_violated:  str,
    corrected_diff:     Diff,
    detection_signal:   enum[test_failure, review_comment, lint_error, silent_bug],
  }],
}
```

#### Dataset 5: Design Rationale and Temporal Context

Each row links a region of code to the historical decisions that explain *why* it is the way it is — the context an agent needs to avoid "cleaning up" intentional complexity.

```
{
  repo:                 str,
  code_region:          {file, span},
  current_form:         str,              # the code as it exists today
  history: [{
    commit:             sha,
    timestamp:          datetime,
    author:             str,
    diff:               Diff,
    message:            str,
    linked_issue:       str | null,       # issue tracker reference
  }],
  rationale: {
    summary:            str,              # e.g. "workaround for upstream bug #1234 in libfoo 2.3"
    constraints:        [str],            # e.g. "cannot use X because of Y"
    still_relevant:     bool,             # is the original reason still valid?
    invalidated_by:     str | null,       # e.g. "fixed in libfoo 2.5"
  },
  naive_refactors: [{                     # plausible "improvements" an agent might attempt
    diff:               Diff,
    why_incorrect:      str,              # what breaks if you apply this
    failure_signal:     str,
  }],
}
```

#### Dataset 6: Cross-Repository Dependency Context

Each row captures a usage of an external library and the external documentation, source, or changelog context needed to use it correctly — especially across versions.

```
{
  consumer_repo:        str,
  dependency:           {name, version},
  usage_location:       {file, span},
  api_used:             fully_qualified_name,
  required_context: [{
    source_type:        enum[source_code, docstring, changelog, migration_guide, issue_thread, example],
    location:           str,              # file path in dependency repo, doc URL, or issue URL
    content:            str,
    relevance:          str,              # e.g. "return type changed in v3.0", "deprecated in favor of X"
  }],
  version_sensitivity: {
    valid_for:          version_range,    # versions where current usage is correct
    breaks_at:          version | null,   # version where behavior changes
    breaking_change:    str | null,       # what changed
  },
  misuse_examples: [{
    diff:               Diff,
    assumption_violated: str,
    failure_signal:     str,
  }],
}
```

---

Dataset 1 is the umbrella — you could in principle derive training signal for any approach from it alone. Datasets 2–6 are vertical-specific: each isolates a distinct axis of non-local context (contracts, impact propagation, conventions, historical rationale, cross-repo dependencies) and provides richer, more structured labels along that axis. Together they cover the full space described in the paragraphs above.

## Reality Check 

The ideal schema above asks for five things per task: a task statement, a point-in-time code/dependency snapshot, a failure signal, a corrected change, and explicit attribution of the missing non-local context. No single public source gives all five, so the practical path is to combine (1) existing benchmarks, (2) mined web data, and (3) synthetic generation pipelines.

| Type | Dataset | Description | Commentary |
| --- | --- | --- | --- |
| Public | [SWE-bench](https://www.swebench.com/original.html) | ~2,294 task instances from 12 popular Python repos (Django, scikit-learn, sympy, etc.). Each instance: a GitHub issue, the PR that resolved it, and a test patch that validates the fix. Provides task + repo snapshot + failure signal + corrected diff. | **Primary evaluation benchmark.** Run agents with/without MCP service, measure resolution-rate delta. Also a source for mining missing-context labels: for each instance we can analyze what non-local information the gold patch relied on that an agent wouldn't see in the edited file alone. Covers aspirational Datasets 1, 3 partially. |
| Public | [SWE-bench-Live](https://huggingface.co/datasets/SWE-bench-Live/SWE-bench-Live) | Continuously updated variant of SWE-bench with more recent issues post-training-cutoff. Same schema (issue, PR, test patch). | **Anti-contamination eval set.** Prevents inflated scores from benchmark leakage into foundation model training data. Use as a held-out evaluation set once our system is tuned on original SWE-bench. |
| Public | [SWE-smith](https://github.com/SWE-bench/SWE-smith) | Toolkit for generating synthetic SWE-bench-style instances via automated code transformations (bug injection, context removal). Can produce instances at scale on arbitrary repos. | **Scale up evaluation + training data.** Original SWE-bench is only ~2K instances; SWE-smith lets us generate orders of magnitude more. Useful for stress-testing retrieval under diverse repo structures. Also useful for generating Dataset 1 (context-attributed failures) synthetically since we control the injected bug and therefore know the ground-truth context. |
| Public | [SWE-Gym-Raw](https://huggingface.co/datasets/SWE-Gym/SWE-Gym-Raw) | Execution environments for SWE-bench instances. Provides Docker setups with pinned dependencies for running tests against agent patches. | **Evaluation infrastructure, not a dataset per se.** Useful for running our eval harness reliably (reproducible environments). Saves us from having to build execution sandboxes ourselves. Low priority for data pipeline ingestion; high priority for eval harness. |
| Public | [SWE-rebench](https://huggingface.co/datasets/nebius/SWE-rebench-leaderboard) | Re-evaluated SWE-bench leaderboard with stricter pass/fail criteria (avoids false positives from flaky tests, overcounting, etc.). | **Meta-resource for calibrating our evaluation.** Not a dataset to ingest. Use their methodology to ensure our eval harness produces trustworthy numbers. Reference only. |
| Public | [RepoBench](https://github.com/Leolty/repobench) | Benchmark for repo-level code completion. Tasks require cross-file context (imports, related functions in other files) to correctly complete a function body. ~11K instances across Python and Java. | **Directly relevant for evaluating code graph retrieval.** Tests exactly the scenario our `get_callers` and `get_contract` tools address: can the system surface the right cross-file context? Good eval set for the indexing layer independent of the full MCP pipeline. Covers aspirational Dataset 2 (contracts/cross-boundary specs). |
| Public | [The Stack v2](https://huggingface.co/datasets/bigcode/the-stack-v2) | ~67.5 TB of permissively licensed source code from Software Heritage. Raw code across hundreds of languages. | **Training resource for code embeddings, not an eval dataset.** If we train or fine-tune our own embedding model for Milvus semantic search, this is the corpus. Also useful for mining conventions at scale (Dataset 4) by observing patterns across many repos. Heavy to work with; use targeted subsets. |
| Public | [Software Heritage Graph](https://docs.softwareheritage.org/devel/swh-export/graph/) | Complete graph of all publicly known software development: repos, commits, directories, files, and their relationships. Available as a graph export (nodes + edges). | **Useful for dependency/impact analysis at scale.** Could power Dataset 3 (downstream impact chains) and Dataset 6 (cross-repo dependency context) by providing the actual call/import graph across the open-source ecosystem. Very heavy; likely only useful in targeted queries via their API or BigQuery export rather than full ingestion. |
| Public | [GH Archive](https://www.gharchive.org/) | Complete GitHub event stream since 2011: PushEvents, PullRequestEvents, IssuesEvents, IssueCommentEvents, etc. Available as JSON via BigQuery or direct download. | **Primary source for scraped training data.** Mine issue->PR->fix chains at scale. Review comments often contain the exact missing-context signal we need ("this breaks because of X in module Y"). Feeds Datasets 1 and 5 (context-attributed failures, design rationale). Also feeds the mental model pipeline: observe how repos evolve. High priority for the offline data pipeline. |
| Public | [deps.dev](https://docs.deps.dev/bigquery/v1/) | Google's dataset of dependency relationships across package ecosystems (npm, PyPI, Go, Maven, Cargo, etc.). Available via BigQuery. Includes dependency graphs, versions, advisories, licenses. | **Directly feeds `get_dependency_context` tool and Dataset 6 (cross-repo dependency context).** When our service indexes a repo's dependencies, deps.dev provides the version graph, known breaking changes, and advisory data. High priority for the dependency index. |
| Public | [CodeSearchNet](https://github.com/github/CodeSearchNet) | ~2M code-docstring pairs across 6 languages (Python, Java, JS, PHP, Go, Ruby). Originally for training code search models. | **Training data for code embedding model.** If we fine-tune embeddings for Milvus, this provides high-quality code+NL pairs for contrastive learning. Also useful for evaluating whether our semantic search retrieves relevant code given natural language queries (which is what `get_context_for_change` does). Medium priority. |
| Synthetic | Mutation-induced failing patches | Generate via mutmut or similar on repos with tests. Inject mutations, run tests, keep failing mutants. Produces (mutation_diff, failing_tests, original_code) triples. | **High-volume source for Dataset 1 and Dataset 3.** We control the perturbation, so we know exactly what was changed and can trace the failure path. Use to build large-scale training data for the retrieval ranker: "given this mutation, what context would have prevented an agent from making the same mistake?" Generation pipeline should run on repos already in our data lake. |
| Synthetic | Mutation-repair pairs with context budgets | Extension of above: for each mutated bug, collect agent fix with limited context vs agent fix with augmented context. Compare outcomes. | **The most directly valuable synthetic dataset.** Produces the exact causal signal we need: "did having context X change the agent's outcome from wrong to right?" This is ground truth for training the ranking in `get_context_for_change`. Expensive to generate (requires running agents), but highest signal-to-noise ratio. |
| Synthetic | Documentation/docstring generation | Generate or extract docstrings, use as training data for learning similarity between code semantics and natural language descriptions. | **Secondary priority.** Useful for fine-tuning the embedding model to better align code and documentation in Milvus. Improves `get_dependency_context` and any NL-based retrieval. Can defer until semantic search is the bottleneck. |
| Scraped | [Closed issues + closing PRs + merge diffs](https://docs.github.com/en/graphql) | Mine via GitHub GraphQL API: issue text, discussion thread, linked PR, review comments, commit diffs. Directly yields (task_description, discussion_context, fix_diff) tuples. | **Primary scraped dataset. High priority.** This is the closest thing to naturally occurring Dataset 1 instances. Review comments are especially valuable: they often say "this breaks X because Y" -- that's a human-labeled missing-context annotation. Feeds training data for retrieval ranking, mental model construction, and convention mining. The offline pipeline should prioritize this source. |

### Operational Ingestion Policy (Current Plan)

To keep evaluation reproducible and costs bounded, Lighthouse applies the following ingestion/recompute policy:

- External benchmark snapshots (for example, fixed SWE-bench releases) are version-pinned and treated as immutable once ingested.
- Rolling scraped sources are ingested incrementally (append/upsert) on recurring schedules.
- Synthetic datasets are refreshed on cadence and re-generated on demand when generators/scoring/schema change.
- Full historical recompute is reserved for schema-breaking changes, transform defects, or explicit correction backfills.
