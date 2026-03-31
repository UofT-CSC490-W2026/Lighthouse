from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import re

REPO_ROOT = Path(__file__).resolve().parents[2]
FAMILIES_ROOT = REPO_ROOT / "packages" / "eval" / "src" / "eval" / "synthetic" / "families"
CONFIG_ROOT = Path(__file__).resolve().parent
GENERATED_ROOT = CONFIG_ROOT / "generated"
PENDING_PATH = CONFIG_ROOT / "pending_configs.txt"
MANIFEST_PATH = CONFIG_ROOT / "generated_manifest.json"

CONTEXT_SOURCES = ("code", "wiki", "combined", "ast", "grep")
CHUNKING_STRATEGIES = ("base", "ast")
CODEGEN_MODELS = (
    "bedrock/us.anthropic.claude-sonnet-4-6",
    "bedrock/amazon.nova-pro-v1:0",
    "bedrock/google.gemma-3-12b-it",
    "openai/gpt-5.4",
)
EMBEDDING_PAIRS = (
    ("bedrock", "amazon.titan-embed-text-v2:0"),
    ("openai", "text-embedding-3-large"),
)

FIXED_REPEAT_COUNT = 3
FIXED_K_VALUES = (1, 2, 3)
FIXED_TASK_COUNT = 30
FIXED_TOP_K = 10

_SAFE_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class ConfigSpec:
    family: str
    context_source: str
    chunking_strategy: str
    codegen_model: str
    embedding_strategy: str
    embedding_model: str


@dataclass(frozen=True)
class FamilyInfo:
    family_name: str
    task_count: int


def _slug(value: str) -> str:
    compact = _SAFE_SLUG_RE.sub("-", value.lower()).strip("-")
    return compact or "x"


def discover_family_infos() -> tuple[FamilyInfo, ...]:
    discovered: list[FamilyInfo] = []
    for child in sorted(FAMILIES_ROOT.iterdir()):
        if not child.is_dir():
            continue
        family_path = child / "family.json"
        if not family_path.is_file():
            continue
        family_raw = json.loads(family_path.read_text(encoding="utf-8"))
        family_name = str(family_raw.get("family_name", child.name.replace("_", "-"))).strip()
        task_count = int(family_raw.get("task_count", 0))
        if task_count < 1:
            raise RuntimeError(f"Invalid task_count in {family_path}: {task_count}")
        discovered.append(FamilyInfo(family_name=family_name, task_count=task_count))
    if not discovered:
        raise RuntimeError(f"No synthetic families discovered under {FAMILIES_ROOT}")
    return tuple(discovered)


def iter_specs() -> tuple[ConfigSpec, ...]:
    specs: list[ConfigSpec] = []
    for family_info in discover_family_infos():
        family = family_info.family_name
        for context_source in CONTEXT_SOURCES:
            for chunking_strategy in CHUNKING_STRATEGIES:
                if context_source == "ast" and chunking_strategy != "ast":
                    continue
                for codegen_model in CODEGEN_MODELS:
                    for embedding_strategy, embedding_model in EMBEDDING_PAIRS:
                        specs.append(
                            ConfigSpec(
                                family=family,
                                context_source=context_source,
                                chunking_strategy=chunking_strategy,
                                codegen_model=codegen_model,
                                embedding_strategy=embedding_strategy,
                                embedding_model=embedding_model,
                            )
                        )
    return tuple(specs)


def config_filename(spec: ConfigSpec) -> str:
    return (
        f"fam-{_slug(spec.family)}"
        f"__ctx-{_slug(spec.context_source)}"
        f"__chunk-{_slug(spec.chunking_strategy)}"
        f"__cg-{_slug(spec.codegen_model)}"
        f"__es-{_slug(spec.embedding_strategy)}"
        f"__em-{_slug(spec.embedding_model)}.json"
    )


def config_payload(spec: ConfigSpec) -> dict[str, object]:
    family_task_counts = {item.family_name: item.task_count for item in discover_family_infos()}
    family_max = family_task_counts[spec.family]
    effective_task_count = min(FIXED_TASK_COUNT, family_max)
    return {
        "families": [spec.family],
        "context_sources": [spec.context_source],
        "chunking_strategies": [spec.chunking_strategy],
        "codegen_models": [spec.codegen_model],
        "embedding_models": [spec.embedding_model],
        "embedding_strategy": spec.embedding_strategy,
        "repeat_count": FIXED_REPEAT_COUNT,
        "k_values": list(FIXED_K_VALUES),
        "task_count": effective_task_count,
        "top_k": FIXED_TOP_K,
    }


def main() -> int:
    GENERATED_ROOT.mkdir(parents=True, exist_ok=True)
    for existing in GENERATED_ROOT.glob("*.json"):
        existing.unlink()

    specs = iter_specs()
    generated_paths: list[Path] = []
    for spec in specs:
        target = GENERATED_ROOT / config_filename(spec)
        target.write_text(
            json.dumps(config_payload(spec), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        generated_paths.append(target)

    pending_entries = [
        str(path.relative_to(REPO_ROOT))
        for path in sorted(generated_paths, key=lambda item: item.name)
    ]
    PENDING_PATH.write_text("\n".join(pending_entries) + "\n", encoding="utf-8")

    family_infos = discover_family_infos()
    requested_vs_effective = {
        item.family_name: {
            "requested_task_count": FIXED_TASK_COUNT,
            "available_task_count": item.task_count,
            "effective_task_count": min(FIXED_TASK_COUNT, item.task_count),
        }
        for item in family_infos
    }

    manifest = {
        "config_count": len(generated_paths),
        "families": sorted(item.family_name for item in family_infos),
        "context_sources": list(CONTEXT_SOURCES),
        "chunking_strategies": list(CHUNKING_STRATEGIES),
        "codegen_models": list(CODEGEN_MODELS),
        "embedding_pairs": [
            {"embedding_strategy": strategy, "embedding_model": model}
            for strategy, model in EMBEDDING_PAIRS
        ],
        "fixed": {
            "repeat_count": FIXED_REPEAT_COUNT,
            "k_values": list(FIXED_K_VALUES),
            "requested_task_count": FIXED_TASK_COUNT,
            "top_k": FIXED_TOP_K,
        },
        "task_count_by_family": requested_vs_effective,
        "pending_file": str(PENDING_PATH.relative_to(REPO_ROOT)),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"Wrote {len(generated_paths)} configs to {GENERATED_ROOT}")
    print(f"Wrote pending queue: {PENDING_PATH}")
    print(f"Wrote manifest: {MANIFEST_PATH}")
    if any(item.task_count < FIXED_TASK_COUNT for item in family_infos):
        print(
            "Note: requested task_count=30 exceeds available tasks for some families; "
            "configs were capped per family (see generated_manifest.json)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
