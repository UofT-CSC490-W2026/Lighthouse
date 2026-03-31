from __future__ import annotations

import argparse
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

CONTEXT_SOURCES_FULL = ("code", "wiki", "combined", "ast", "grep")
CHUNKING_STRATEGIES_FULL = ("base", "ast")
CODEGEN_MODELS_FULL = (
    "bedrock/us.anthropic.claude-sonnet-4-6",
    "bedrock/amazon.nova-pro-v1:0",
    "bedrock/google.gemma-3-12b-it",
    "openai/gpt-5.4",
)
EMBEDDING_PAIRS_FULL = (
    ("bedrock", "amazon.titan-embed-text-v2:0"),
    ("openai", "text-embedding-3-large"),
)

CONTEXT_SOURCES_SIMPLIFIED = ("combined", "grep")
CHUNKING_STRATEGIES_SIMPLIFIED = ("ast",)
CODEGEN_MODELS_SIMPLIFIED = CODEGEN_MODELS_FULL
EMBEDDING_PAIRS_SIMPLIFIED = (("openai", "text-embedding-3-large"),)

FIXED_TASK_COUNT = 30
FIXED_TOP_K = 10

FIXED_REPEAT_COUNT_FULL = 3
FIXED_K_VALUES_FULL = (1, 2, 3)

FIXED_REPEAT_COUNT_SIMPLIFIED = 1
FIXED_K_VALUES_SIMPLIFIED = (1,)

_SAFE_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class Profile:
    name: str
    context_sources: tuple[str, ...]
    chunking_strategies: tuple[str, ...]
    codegen_models: tuple[str, ...]
    embedding_pairs: tuple[tuple[str, str], ...]
    repeat_count: int
    k_values: tuple[int, ...]


PROFILES: dict[str, Profile] = {
    "full": Profile(
        name="full",
        context_sources=CONTEXT_SOURCES_FULL,
        chunking_strategies=CHUNKING_STRATEGIES_FULL,
        codegen_models=CODEGEN_MODELS_FULL,
        embedding_pairs=EMBEDDING_PAIRS_FULL,
        repeat_count=FIXED_REPEAT_COUNT_FULL,
        k_values=FIXED_K_VALUES_FULL,
    ),
    "simplified": Profile(
        name="simplified",
        context_sources=CONTEXT_SOURCES_SIMPLIFIED,
        chunking_strategies=CHUNKING_STRATEGIES_SIMPLIFIED,
        codegen_models=CODEGEN_MODELS_SIMPLIFIED,
        embedding_pairs=EMBEDDING_PAIRS_SIMPLIFIED,
        repeat_count=FIXED_REPEAT_COUNT_SIMPLIFIED,
        k_values=FIXED_K_VALUES_SIMPLIFIED,
    ),
}


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


def iter_specs(profile: Profile) -> tuple[ConfigSpec, ...]:
    specs: list[ConfigSpec] = []
    for family_info in discover_family_infos():
        family = family_info.family_name
        for context_source in profile.context_sources:
            for chunking_strategy in profile.chunking_strategies:
                if context_source == "ast" and chunking_strategy != "ast":
                    continue
                for codegen_model in profile.codegen_models:
                    for embedding_strategy, embedding_model in profile.embedding_pairs:
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


def config_payload(spec: ConfigSpec, profile: Profile) -> dict[str, object]:
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
        "repeat_count": profile.repeat_count,
        "k_values": list(profile.k_values),
        "task_count": effective_task_count,
        "top_k": FIXED_TOP_K,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate singleton synthetic matrix configs + queue.")
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES.keys()),
        default="full",
        help="full: all contexts/embeddings/repeats; simplified: combined+grep, openai+3-large, AST, pass@1",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    profile = PROFILES[args.profile]

    GENERATED_ROOT.mkdir(parents=True, exist_ok=True)
    for existing in GENERATED_ROOT.glob("*.json"):
        existing.unlink()

    specs = iter_specs(profile)
    generated_paths: list[Path] = []
    for spec in specs:
        target = GENERATED_ROOT / config_filename(spec)
        target.write_text(
            json.dumps(config_payload(spec, profile), indent=2, sort_keys=True) + "\n",
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
        "profile": profile.name,
        "config_count": len(generated_paths),
        "families": sorted(item.family_name for item in family_infos),
        "context_sources": list(profile.context_sources),
        "chunking_strategies": list(profile.chunking_strategies),
        "codegen_models": list(profile.codegen_models),
        "embedding_pairs": [
            {"embedding_strategy": strategy, "embedding_model": model}
            for strategy, model in profile.embedding_pairs
        ],
        "fixed": {
            "repeat_count": profile.repeat_count,
            "k_values": list(profile.k_values),
            "requested_task_count": FIXED_TASK_COUNT,
            "top_k": FIXED_TOP_K,
        },
        "task_count_by_family": requested_vs_effective,
        "pending_file": str(PENDING_PATH.relative_to(REPO_ROOT)),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"Profile: {profile.name}")
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
