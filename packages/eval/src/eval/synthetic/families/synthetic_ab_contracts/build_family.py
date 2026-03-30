from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent


FAMILY_DIR = Path(__file__).resolve().parent
TASKS_PATH = FAMILY_DIR / "tasks.json"
FAMILY_CONFIG_PATH = FAMILY_DIR / "family.json"
REPO_A_TESTS_DIR = FAMILY_DIR / "repo_a_template" / "tests"

GENERATED_START = "# BEGIN GENERATED CONTRACT CASES"
GENERATED_END = "# END GENERATED CONTRACT CASES"
ORIGINAL_TASK_IDS = tuple(f"{index:03d}" for index in range(1, 11))


@dataclass(frozen=True)
class CaseSpec:
    case_id: str
    description: str
    params: tuple[object, ...]
    expected: object | None = None
    test_name: str | None = None


@dataclass(frozen=True)
class GroupSpec:
    original_task_id: str
    extra_task_ids: tuple[str, ...]
    title_prefix: str
    problem_intro: str
    extra_target_template: str
    cases: tuple[CaseSpec, ...]


def main() -> None:
    original_tasks = _load_original_tasks()
    family_config = json.loads(FAMILY_CONFIG_PATH.read_text(encoding="utf-8"))
    task_entries = sorted(
        [
            *original_tasks.values(),
            *build_extra_task_entries(original_tasks),
        ],
        key=lambda entry: int(str(entry["task_id"]).split("-")[-1]),
    )
    payload = {
        "family_name": family_config["family_name"],
        "family_version": family_config["family_version"],
        "generation_config": {
            "task_type": family_config["task_type"],
            "task_count": family_config["task_count"],
            "shared_library_repo_count": family_config["shared_library_repo_count"],
            "consumer_repo_mode": family_config["consumer_repo_mode"],
            "python_version_target": family_config["python_version_target"],
            "context_modes": family_config["context_modes"],
            "seed": family_config["seed"],
        },
        "tasks": task_entries,
    }
    TASKS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    for path, block in test_file_blocks().items():
        _upsert_generated_block(path, block)


def build_extra_task_entries(
    original_tasks: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for group in group_specs():
        template_task = original_tasks[group.original_task_id]
        if len(group.extra_task_ids) != len(group.cases):
            raise ValueError(
                f"Task id count does not match case count for original task {group.original_task_id}"
            )
        for task_id, case in zip(group.extra_task_ids, group.cases, strict=True):
            target_test_name = case.test_name or group.extra_target_template.split("::", 1)[1]
            pytest_target = group.extra_target_template.format(
                test_name=target_test_name,
                case_id=case.case_id,
            )
            numeric_task_id = int(task_id)
            description = case.description.rstrip(".")
            entries.append(
                {
                    "task_id": f"ab-contracts-{task_id}",
                    "task_type": template_task["task_type"],
                    "title": f"{group.title_prefix} {description}",
                    "problem_statement": (
                        f"{group.problem_intro} Fix the consumer so it {description}."
                    ),
                    "repo_a_name": f"synthetic/consumer-app-{task_id}",
                    "repo_b_name": template_task["repo_b_name"],
                    "repo_a_id": 910000000 + numeric_task_id,
                    "repo_b_id": template_task["repo_b_id"],
                    "branch": template_task["branch"],
                    "buggy_patch_path": template_task["buggy_patch_path"],
                    "gold_patch_path": template_task["gold_patch_path"],
                    "pytest_targets": [pytest_target],
                    "expected_relevant_files": template_task["expected_relevant_files"],
                    "expected_relevant_symbols": template_task["expected_relevant_symbols"],
                    "context_modes_supported": template_task["context_modes_supported"],
                    "visible_api_names": template_task["visible_api_names"],
                    "test_context": f"The failing test checks that it {description}.",
                }
            )
    return entries


def test_file_blocks() -> dict[Path, str]:
    return {
        REPO_A_TESTS_DIR / "test_progress.py": _render_output_block(
            test_name="test_render_progress_badge_contract_cases",
            arg_names=("progress",),
            cases=PROGRESS_CASES,
            assertion="render_progress_badge(progress) == expected",
        ),
        REPO_A_TESTS_DIR / "test_retries.py": _render_output_block(
            test_name="test_describe_retry_delay_contract_cases",
            arg_names=("header",),
            cases=RETRY_CASES,
            assertion="describe_retry_delay(header) == expected",
        ),
        REPO_A_TESTS_DIR / "test_usernames.py": _render_output_block(
            test_name="test_canonical_username_contract_cases",
            arg_names=("raw",),
            cases=USERNAME_CASES,
            assertion="canonical_username(raw) == expected",
        ),
        REPO_A_TESTS_DIR / "test_emails.py": _render_output_block(
            test_name="test_primary_contact_contract_cases",
            arg_names=("emails",),
            cases=EMAIL_CASES,
            assertion="primary_contact(emails) == expected",
        ),
        REPO_A_TESTS_DIR / "test_flags.py": "\n\n".join(
            [
                _render_output_block(
                    test_name="test_is_beta_enabled_false_contract_cases",
                    arg_names=("raw",),
                    cases=FLAG_FALSE_CASES,
                    assertion="is_beta_enabled(raw) is expected",
                ),
                _render_invalid_block(
                    test_name="test_is_beta_enabled_invalid_contract_cases",
                    arg_name="raw",
                    cases=FLAG_INVALID_CASES,
                    assertion="is_beta_enabled(raw)",
                ),
            ]
        ),
        REPO_A_TESTS_DIR / "test_timeouts.py": _render_output_block(
            test_name="test_client_timeout_ms_contract_cases",
            arg_names=("seconds",),
            cases=TIMEOUT_CASES,
            assertion="client_timeout_ms(seconds) == expected",
        ),
        REPO_A_TESTS_DIR / "test_tags.py": _render_output_block(
            test_name="test_normalized_tag_line_contract_cases",
            arg_names=("tags",),
            cases=TAG_CASES,
            assertion="normalized_tag_line(tags) == expected",
        ),
        REPO_A_TESTS_DIR / "test_ratios.py": _render_output_block(
            test_name="test_ratio_or_label_contract_cases",
            arg_names=("numerator", "denominator", "default"),
            cases=RATIO_CASES,
            assertion="ratio_or_label(numerator, denominator, default=default) == expected",
        ),
        REPO_A_TESTS_DIR / "test_cache_keys.py": _render_output_block(
            test_name="test_session_cache_key_contract_cases",
            arg_names=("user_id",),
            cases=CACHE_KEY_CASES,
            assertion="session_cache_key(user_id) == expected",
        ),
        REPO_A_TESTS_DIR / "test_statuses.py": _render_output_block(
            test_name="test_badge_color_contract_cases",
            arg_names=("status",),
            cases=STATUS_CASES,
            assertion="badge_color(status) == expected",
        ),
    }


def _render_output_block(
    *,
    test_name: str,
    arg_names: tuple[str, ...],
    cases: tuple[CaseSpec, ...],
    assertion: str,
) -> str:
    names_literal = "(" + ", ".join(repr(name) for name in (*arg_names, "expected")) + ")"
    rendered_cases = "\n".join(
        _render_pytest_param((*case.params, case.expected), case.case_id) for case in cases
    )
    params_signature = ", ".join((*arg_names, "expected"))
    return dedent(
        f"""
        @pytest.mark.parametrize(
            {names_literal},
            [
        {rendered_cases}
            ],
        )
        def {test_name}({params_signature}) -> None:
            assert {assertion}
        """
    ).strip()


def _render_invalid_block(
    *,
    test_name: str,
    arg_name: str,
    cases: tuple[CaseSpec, ...],
    assertion: str,
) -> str:
    rendered_cases = "\n".join(
        _render_pytest_param(case.params, case.case_id) for case in cases
    )
    return dedent(
        f"""
        @pytest.mark.parametrize(
            {arg_name!r},
            [
        {rendered_cases}
            ],
        )
        def {test_name}({arg_name}) -> None:
            with pytest.raises(ValueError):
                {assertion}
        """
    ).strip()


def _render_pytest_param(values: tuple[object, ...], case_id: str) -> str:
    # Use ascii() so control characters in strings (e.g., "\n", "\t") are escaped
    # in generated source code instead of being injected as raw newlines/tabs.
    rendered_values = ", ".join(ascii(value) for value in values)
    return f"        pytest.param({rendered_values}, id={case_id!r}),"


def _upsert_generated_block(path: Path, block: str) -> None:
    original_text = path.read_text(encoding="utf-8")
    text = _ensure_pytest_import(original_text)
    generated_block = f"{GENERATED_START}\n{block.rstrip()}\n{GENERATED_END}"
    pattern = re.compile(
        rf"{re.escape(GENERATED_START)}\n.*?\n{re.escape(GENERATED_END)}",
        flags=re.DOTALL,
    )
    if pattern.search(text):
        # Use a callable replacement so backslashes in generated content
        # (e.g., "\\n", "\\t") are preserved literally.
        updated = pattern.sub(lambda _match: generated_block, text)
    else:
        updated = text.rstrip() + "\n\n\n" + generated_block + "\n"
    path.write_text(updated, encoding="utf-8")


def _ensure_pytest_import(text: str) -> str:
    if "import pytest" in text:
        return text
    future_import = "from __future__ import annotations\n"
    if future_import in text:
        return text.replace(future_import, future_import + "\nimport pytest\n", 1)
    return "import pytest\n\n" + text


def _load_original_tasks() -> dict[str, dict[str, object]]:
    raw = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    tasks = raw.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("Expected a tasks list in tasks.json")
    originals: dict[str, dict[str, object]] = {}
    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("task_id", ""))
        suffix = task_id.split("-")[-1]
        if suffix in ORIGINAL_TASK_IDS:
            originals[suffix] = task
    missing = [task_id for task_id in ORIGINAL_TASK_IDS if task_id not in originals]
    if missing:
        raise ValueError(f"Missing original synthetic tasks: {', '.join(missing)}")
    return originals


def group_specs() -> tuple[GroupSpec, ...]:
    return (
        GroupSpec(
            original_task_id="001",
            extra_task_ids=tuple(f"{task_id:03d}" for task_id in range(11, 20)),
            title_prefix="Progress badge should",
            problem_intro=(
                "consumer_app.progress is misusing providerlib.metrics.clamp_percentage."
            ),
            extra_target_template=(
                "tests/test_progress.py::test_render_progress_badge_contract_cases[{case_id}]"
            ),
            cases=PROGRESS_CASES,
        ),
        GroupSpec(
            original_task_id="002",
            extra_task_ids=tuple(f"{task_id:03d}" for task_id in range(20, 29)),
            title_prefix="Retry delay should",
            problem_intro=(
                "consumer_app.retries is no longer preserving the default and minimum "
                "semantics of providerlib.http.parse_retry_header."
            ),
            extra_target_template=(
                "tests/test_retries.py::test_describe_retry_delay_contract_cases[{case_id}]"
            ),
            cases=RETRY_CASES,
        ),
        GroupSpec(
            original_task_id="003",
            extra_task_ids=tuple(f"{task_id:03d}" for task_id in range(29, 38)),
            title_prefix="Usernames should",
            problem_intro=(
                "consumer_app.usernames is bypassing providerlib.identity.normalize_username."
            ),
            extra_target_template=(
                "tests/test_usernames.py::test_canonical_username_contract_cases[{case_id}]"
            ),
            cases=USERNAME_CASES,
        ),
        GroupSpec(
            original_task_id="004",
            extra_task_ids=tuple(f"{task_id:03d}" for task_id in range(38, 47)),
            title_prefix="Primary email selection should",
            problem_intro=(
                "consumer_app.emails is no longer delegating cleanup and fallback logic to "
                "providerlib.identity.choose_primary_email."
            ),
            extra_target_template=(
                "tests/test_emails.py::test_primary_contact_contract_cases[{case_id}]"
            ),
            cases=EMAIL_CASES,
        ),
        GroupSpec(
            original_task_id="005",
            extra_task_ids=tuple(f"{task_id:03d}" for task_id in range(47, 56)),
            title_prefix="Feature flags should",
            problem_intro=(
                "consumer_app.flags is bypassing providerlib.http.parse_feature_flag."
            ),
            extra_target_template="tests/test_flags.py::{test_name}[{case_id}]",
            cases=(*FLAG_FALSE_CASES, *FLAG_INVALID_CASES),
        ),
        GroupSpec(
            original_task_id="006",
            extra_task_ids=tuple(f"{task_id:03d}" for task_id in range(56, 65)),
            title_prefix="Timeout conversion should",
            problem_intro=(
                "consumer_app.timeouts is misusing providerlib.metrics.seconds_to_timeout_ms."
            ),
            extra_target_template=(
                "tests/test_timeouts.py::test_client_timeout_ms_contract_cases[{case_id}]"
            ),
            cases=TIMEOUT_CASES,
        ),
        GroupSpec(
            original_task_id="007",
            extra_task_ids=tuple(f"{task_id:03d}" for task_id in range(65, 74)),
            title_prefix="Tag rendering should",
            problem_intro=(
                "consumer_app.tags is reordering the output of providerlib.identity.normalize_tags."
            ),
            extra_target_template=(
                "tests/test_tags.py::test_normalized_tag_line_contract_cases[{case_id}]"
            ),
            cases=TAG_CASES,
        ),
        GroupSpec(
            original_task_id="008",
            extra_task_ids=tuple(f"{task_id:03d}" for task_id in range(74, 83)),
            title_prefix="Ratio fallback should",
            problem_intro=(
                "consumer_app.ratios is no longer preserving the caller-supplied default when "
                "providerlib.math_utils.safe_divide cannot divide."
            ),
            extra_target_template=(
                "tests/test_ratios.py::test_ratio_or_label_contract_cases[{case_id}]"
            ),
            cases=RATIO_CASES,
        ),
        GroupSpec(
            original_task_id="009",
            extra_task_ids=tuple(f"{task_id:03d}" for task_id in range(83, 92)),
            title_prefix="Session cache keys should",
            problem_intro=(
                "consumer_app.cache_keys is bypassing providerlib.cache.build_cache_key."
            ),
            extra_target_template=(
                "tests/test_cache_keys.py::test_session_cache_key_contract_cases[{case_id}]"
            ),
            cases=CACHE_KEY_CASES,
        ),
        GroupSpec(
            original_task_id="010",
            extra_task_ids=tuple(f"{task_id:03d}" for task_id in range(92, 101)),
            title_prefix="Badge colors should",
            problem_intro=(
                "consumer_app.statuses is returning raw status text instead of using "
                "providerlib.ui.status_to_color."
            ),
            extra_target_template=(
                "tests/test_statuses.py::test_badge_color_contract_cases[{case_id}]"
            ),
            cases=STATUS_CASES,
        ),
    )


PROGRESS_CASES = (
    CaseSpec(
        case_id="clamps-negative-values-to-zero",
        description="clamp negative values to zero before rendering",
        params=(-5,),
        expected="0% complete",
    ),
    CaseSpec(
        case_id="clamps-large-values-to-hundred",
        description="clamp values above one hundred to one hundred before rendering",
        params=(250,),
        expected="100% complete",
    ),
    CaseSpec(
        case_id="rounds-up-fractional-progress",
        description="round fractional progress values to the nearest whole percent",
        params=(42.6,),
        expected="43% complete",
    ),
    CaseSpec(
        case_id="rounds-down-small-fractions",
        description="round very small fractional values down to zero percent",
        params=(0.4,),
        expected="0% complete",
    ),
    CaseSpec(
        case_id="rounds-up-small-fractions",
        description="round small fractional values up when they cross the half-percent boundary",
        params=(0.6,),
        expected="1% complete",
    ),
    CaseSpec(
        case_id="preserves-zero-progress",
        description="keep zero progress as a whole-percentage badge",
        params=(0,),
        expected="0% complete",
    ),
    CaseSpec(
        case_id="keeps-integer-progress-values",
        description="render integer progress values without changing the provider result",
        params=(7,),
        expected="7% complete",
    ),
    CaseSpec(
        case_id="handles-exact-hundred",
        description="preserve exact one-hundred-percent progress badges",
        params=(100,),
        expected="100% complete",
    ),
    CaseSpec(
        case_id="rounds-teen-fractions",
        description="round multi-digit fractional progress using provider semantics",
        params=(15.2,),
        expected="15% complete",
    ),
)

RETRY_CASES = (
    CaseSpec(
        case_id="defaults-empty-headers-to-one-second",
        description="default empty retry headers to one second",
        params=("",),
        expected="retry in 1 second",
    ),
    CaseSpec(
        case_id="defaults-blank-headers-to-one-second",
        description="default blank retry headers to one second",
        params=("   ",),
        expected="retry in 1 second",
    ),
    CaseSpec(
        case_id="defaults-tab-headers-to-one-second",
        description="default tab-only retry headers to one second",
        params=("\t",),
        expected="retry in 1 second",
    ),
    CaseSpec(
        case_id="defaults-newline-headers-to-one-second",
        description="default newline-only retry headers to one second",
        params=("\n",),
        expected="retry in 1 second",
    ),
    CaseSpec(
        case_id="clamps-zero-retry-values-to-one-second",
        description="clamp zero-second retry headers up to one second",
        params=("0",),
        expected="retry in 1 second",
    ),
    CaseSpec(
        case_id="clamps-signed-zero-retry-values-to-one-second",
        description="clamp signed zero retry headers up to one second",
        params=("+0",),
        expected="retry in 1 second",
    ),
    CaseSpec(
        case_id="clamps-negative-retry-values-to-one-second",
        description="clamp negative retry headers up to one second",
        params=("-3",),
        expected="retry in 1 second",
    ),
    CaseSpec(
        case_id="clamps-zero-with-whitespace-to-one-second",
        description="clamp zero retry headers with surrounding whitespace up to one second",
        params=(" 0 ",),
        expected="retry in 1 second",
    ),
    CaseSpec(
        case_id="clamps-negative-with-whitespace-to-one-second",
        description="clamp negative retry headers with surrounding whitespace up to one second",
        params=(" -9 ",),
        expected="retry in 1 second",
    ),
)

USERNAME_CASES = (
    CaseSpec(
        case_id="collapses-double-spaces-in-usernames",
        description="collapse repeated internal spaces in usernames",
        params=("Mary   Jane",),
        expected="mary jane",
    ),
    CaseSpec(
        case_id="collapses-leading-and-internal-spaces",
        description="trim and collapse leading and internal spaces in usernames",
        params=("  ONE   TWO  ",),
        expected="one two",
    ),
    CaseSpec(
        case_id="collapses-tabs-in-usernames",
        description="collapse tab-separated usernames into single spaces",
        params=("\tTabbed\tUser\t",),
        expected="tabbed user",
    ),
    CaseSpec(
        case_id="collapses-newlines-in-usernames",
        description="collapse newline-separated usernames into single spaces",
        params=("Line\nBreak",),
        expected="line break",
    ),
    CaseSpec(
        case_id="collapses-mixed-whitespace",
        description="collapse mixed whitespace in usernames into single spaces",
        params=("Mix\t of\nWhitespace",),
        expected="mix of whitespace",
    ),
    CaseSpec(
        case_id="preserves-single-space-separators",
        description="preserve single spaces after collapsing repeated separators",
        params=("Double   middle",),
        expected="double middle",
    ),
    CaseSpec(
        case_id="normalizes-multiword-usernames",
        description="normalize multiword usernames while keeping word boundaries",
        params=("Already   lower   case",),
        expected="already lower case",
    ),
    CaseSpec(
        case_id="strips-and-collapses-surrounding-whitespace",
        description="strip surrounding whitespace and collapse internal spacing in usernames",
        params=("  spaced    out   user ",),
        expected="spaced out user",
    ),
    CaseSpec(
        case_id="collapses-four-word-usernames",
        description="collapse repeated spacing across four-word usernames",
        params=("One   Two   Three   Four",),
        expected="one two three four",
    ),
)

EMAIL_CASES = (
    CaseSpec(
        case_id="skips-empty-first-emails",
        description="skip empty first email entries",
        params=(["", "support@example.com"],),
        expected="support@example.com",
    ),
    CaseSpec(
        case_id="skips-whitespace-only-first-emails",
        description="skip whitespace-only first email entries",
        params=(["   ", "ops@example.com"],),
        expected="ops@example.com",
    ),
    CaseSpec(
        case_id="lowercases-uppercase-primary-emails",
        description="lowercase uppercase primary email addresses",
        params=(["ADMIN@Example.com", "backup@example.com"],),
        expected="admin@example.com",
    ),
    CaseSpec(
        case_id="trims-surrounding-spaces-on-primary-emails",
        description="trim surrounding spaces on primary email addresses",
        params=(["  MIXED@Example.com  ", "backup@example.com"],),
        expected="mixed@example.com",
    ),
    CaseSpec(
        case_id="skips-blank-values-before-valid-emails",
        description="skip blank values before the first valid email address",
        params=(["", "  TEAM@EXAMPLE.COM "],),
        expected="team@example.com",
    ),
    CaseSpec(
        case_id="skips-tab-only-values-before-valid-emails",
        description="skip tab-only values before the first valid email address",
        params=(["\t", "Second@Example.com"],),
        expected="second@example.com",
    ),
    CaseSpec(
        case_id="lowercases-first-valid-mixed-case-emails",
        description="lowercase the first valid mixed-case email address",
        params=(["First@Example.com", "backup@example.com"],),
        expected="first@example.com",
    ),
    CaseSpec(
        case_id="trims-first-valid-lowercase-emails",
        description="trim the first valid email address before returning it",
        params=(["  first@example.com  ", "backup@example.com"],),
        expected="first@example.com",
    ),
    CaseSpec(
        case_id="skips-multiple-blank-values-before-valid-emails",
        description="skip multiple blank values before the first valid email address",
        params=(["", "", "third@example.com"],),
        expected="third@example.com",
    ),
)

FLAG_FALSE_CASES = (
    CaseSpec(
        case_id="parses-uppercase-off-values",
        description="parse uppercase off values as disabled",
        params=("OFF",),
        expected=False,
        test_name="test_is_beta_enabled_false_contract_cases",
    ),
    CaseSpec(
        case_id="parses-false-literals-as-disabled",
        description="parse false literals as disabled",
        params=("false",),
        expected=False,
        test_name="test_is_beta_enabled_false_contract_cases",
    ),
    CaseSpec(
        case_id="parses-disabled-literals-as-disabled",
        description="parse disabled literals as disabled",
        params=("disabled",),
        expected=False,
        test_name="test_is_beta_enabled_false_contract_cases",
    ),
    CaseSpec(
        case_id="parses-no-literals-as-disabled",
        description="parse no literals as disabled",
        params=("no",),
        expected=False,
        test_name="test_is_beta_enabled_false_contract_cases",
    ),
    CaseSpec(
        case_id="parses-zero-literals-as-disabled",
        description="parse zero literals as disabled",
        params=("0",),
        expected=False,
        test_name="test_is_beta_enabled_false_contract_cases",
    ),
    CaseSpec(
        case_id="trims-off-values-before-parsing",
        description="trim off values before parsing them as disabled",
        params=("  off  ",),
        expected=False,
        test_name="test_is_beta_enabled_false_contract_cases",
    ),
)

FLAG_INVALID_CASES = (
    CaseSpec(
        case_id="rejects-unknown-flag-words",
        description="reject unknown feature flag words",
        params=("maybe",),
        test_name="test_is_beta_enabled_invalid_contract_cases",
    ),
    CaseSpec(
        case_id="rejects-blank-flag-values",
        description="reject blank feature flag values",
        params=("   ",),
        test_name="test_is_beta_enabled_invalid_contract_cases",
    ),
    CaseSpec(
        case_id="rejects-partial-flag-tokens",
        description="reject partial feature flag tokens",
        params=("of",),
        test_name="test_is_beta_enabled_invalid_contract_cases",
    ),
)

TIMEOUT_CASES = (
    CaseSpec(
        case_id="converts-one-second-values-to-milliseconds",
        description="convert one-second timeout values to milliseconds",
        params=(1,),
        expected=1000,
    ),
    CaseSpec(
        case_id="converts-half-second-values-to-milliseconds",
        description="convert half-second timeout values to milliseconds",
        params=(0.5,),
        expected=500,
    ),
    CaseSpec(
        case_id="converts-fractional-seconds-with-rounding",
        description="convert fractional timeout values using provider rounding semantics",
        params=(2.25,),
        expected=2250,
    ),
    CaseSpec(
        case_id="converts-ten-second-values-to-milliseconds",
        description="convert ten-second timeout values to milliseconds",
        params=(10,),
        expected=10000,
    ),
    CaseSpec(
        case_id="converts-millisecond-scale-fractions-correctly",
        description="convert millisecond-scale fractional timeout values correctly",
        params=(0.001,),
        expected=1,
    ),
    CaseSpec(
        case_id="converts-repeating-fractions-to-milliseconds",
        description="convert repeating fractional timeout values to milliseconds",
        params=(3.333,),
        expected=3333,
    ),
    CaseSpec(
        case_id="converts-decimal-seconds-with-rounding",
        description="convert decimal timeout values without changing their units",
        params=(2.6,),
        expected=2600,
    ),
    CaseSpec(
        case_id="converts-quarter-second-values-to-milliseconds",
        description="convert quarter-second timeout values to milliseconds",
        params=(0.25,),
        expected=250,
    ),
    CaseSpec(
        case_id="converts-large-fractional-values-to-milliseconds",
        description="convert larger fractional timeout values to milliseconds",
        params=(7.75,),
        expected=7750,
    ),
)

TAG_CASES = (
    CaseSpec(
        case_id="preserves-beta-before-alpha-order",
        description="preserve beta-before-alpha tag order from the provider",
        params=(["Beta Team", "Alpha Team"],),
        expected="beta-team, alpha-team",
    ),
    CaseSpec(
        case_id="preserves-input-order-across-three-tags",
        description="preserve provider order across three unsorted tags",
        params=(["Gamma", "Beta", "Alpha"],),
        expected="gamma, beta, alpha",
    ),
    CaseSpec(
        case_id="keeps-first-seen-order-when-duplicates-appear",
        description="keep first-seen provider order when duplicate tags appear",
        params=(["Ops", "Alpha", "ops", "beta"],),
        expected="ops, alpha, beta",
    ),
    CaseSpec(
        case_id="preserves-zulu-echo-delta-order",
        description="preserve unsorted zulu-echo-delta provider order",
        params=(["Zulu", "Echo", "Delta"],),
        expected="zulu, echo, delta",
    ),
    CaseSpec(
        case_id="preserves-first-seen-multiword-order",
        description="preserve first-seen order for multiword provider tags",
        params=(["Two Words", "One Word", "two words"],),
        expected="two-words, one-word",
    ),
    CaseSpec(
        case_id="preserves-provider-order-for-mixed-case-tags",
        description="preserve provider order for mixed-case tags",
        params=(["Kappa", "alpha", "Beta"],),
        expected="kappa, alpha, beta",
    ),
    CaseSpec(
        case_id="preserves-late-early-middle-order",
        description="preserve late-early-middle provider order",
        params=(["Late", "Early", "Middle"],),
        expected="late, early, middle",
    ),
    CaseSpec(
        case_id="keeps-duplicates-collapsed-without-resorting",
        description="collapse duplicates without resorting provider-defined tags",
        params=(["Zed", "Able", "zed", "Baker"],),
        expected="zed, able, baker",
    ),
    CaseSpec(
        case_id="preserves-multiword-provider-order",
        description="preserve provider order for multiword tags",
        params=(["Road Runner", "Acme Corp", "road runner"],),
        expected="road-runner, acme-corp",
    ),
)

RATIO_CASES = (
    CaseSpec(
        case_id="preserves-zero-fallback-labels",
        description="preserve custom zero-denominator fallback labels",
        params=(1, 0, "zero"),
        expected="zero",
    ),
    CaseSpec(
        case_id="preserves-missing-fallback-labels",
        description="preserve custom missing fallback labels",
        params=(9, 0, "missing"),
        expected="missing",
    ),
    CaseSpec(
        case_id="preserves-unavailable-fallback-labels",
        description="preserve unavailable fallback labels when division is impossible",
        params=(5, 0, "unavailable"),
        expected="unavailable",
    ),
    CaseSpec(
        case_id="preserves-no-ratio-fallback-labels",
        description="preserve no-ratio fallback labels when division is impossible",
        params=(3, 0, "no ratio"),
        expected="no ratio",
    ),
    CaseSpec(
        case_id="preserves-dash-fallback-labels",
        description="preserve dash fallback labels when division is impossible",
        params=(7, 0, "--"),
        expected="--",
    ),
    CaseSpec(
        case_id="preserves-empty-fallback-labels",
        description="preserve empty-state fallback labels when division is impossible",
        params=(12, 0, "empty"),
        expected="empty",
    ),
    CaseSpec(
        case_id="preserves-unknown-fallback-labels",
        description="preserve unknown fallback labels when division is impossible",
        params=(100, 0, "unknown"),
        expected="unknown",
    ),
    CaseSpec(
        case_id="preserves-undefined-fallback-labels",
        description="preserve undefined fallback labels when division is impossible",
        params=(2, 0, "undefined"),
        expected="undefined",
    ),
    CaseSpec(
        case_id="preserves-custom-symbolic-fallback-labels",
        description="preserve custom symbolic fallback labels when division is impossible",
        params=(42, 0, "n/a*"),
        expected="n/a*",
    ),
)

CACHE_KEY_CASES = (
    CaseSpec(
        case_id="lowercases-simple-identifiers",
        description="lowercase simple cache key identifiers",
        params=("Bob",),
        expected="session:bob:v1",
    ),
    CaseSpec(
        case_id="trims-and-lowercases-uppercase-identifiers",
        description="trim and lowercase uppercase cache key identifiers",
        params=("  CAROL",),
        expected="session:carol:v1",
    ),
    CaseSpec(
        case_id="trims-surrounding-whitespace-from-identifiers",
        description="trim surrounding whitespace from cache key identifiers",
        params=(" dave ",),
        expected="session:dave:v1",
    ),
    CaseSpec(
        case_id="preserves-spaces-while-lowercasing-identifiers",
        description="preserve internal spaces while lowercasing cache key identifiers",
        params=("Eve Adams",),
        expected="session:eve adams:v1",
    ),
    CaseSpec(
        case_id="trims-uppercase-identifiers-before-versioning",
        description="trim uppercase cache key identifiers before appending the version suffix",
        params=(" FRANK ",),
        expected="session:frank:v1",
    ),
    CaseSpec(
        case_id="appends-provider-version-for-simple-identifiers",
        description="append the provider version suffix for simple identifiers",
        params=("Grace",),
        expected="session:grace:v1",
    ),
    CaseSpec(
        case_id="appends-provider-version-for-mixed-case-identifiers",
        description="append the provider version suffix for mixed-case identifiers",
        params=("Heidi",),
        expected="session:heidi:v1",
    ),
    CaseSpec(
        case_id="trims-trailing-whitespace-before-versioning",
        description="trim trailing whitespace from identifiers before versioning",
        params=(" IVAN\t",),
        expected="session:ivan:v1",
    ),
    CaseSpec(
        case_id="preserves-email-style-identifiers-with-versioning",
        description="preserve email-style identifiers while appending the provider version suffix",
        params=("Judy@example.com",),
        expected="session:judy@example.com:v1",
    ),
)

STATUS_CASES = (
    CaseSpec(
        case_id="maps-lowercase-queued-statuses",
        description="map queued statuses to slate badge colors",
        params=("queued",),
        expected="slate",
    ),
    CaseSpec(
        case_id="maps-lowercase-running-statuses",
        description="map running statuses to blue badge colors",
        params=("running",),
        expected="blue",
    ),
    CaseSpec(
        case_id="maps-lowercase-succeeded-statuses",
        description="map succeeded statuses to green badge colors",
        params=("succeeded",),
        expected="green",
    ),
    CaseSpec(
        case_id="maps-titlecase-failed-statuses",
        description="map failed statuses to red badge colors",
        params=("Failed",),
        expected="red",
    ),
    CaseSpec(
        case_id="normalizes-titlecase-queued-statuses",
        description="normalize queued status casing before looking up badge colors",
        params=("Queued",),
        expected="slate",
    ),
    CaseSpec(
        case_id="normalizes-titlecase-running-statuses",
        description="normalize running status casing before looking up badge colors",
        params=("Running",),
        expected="blue",
    ),
    CaseSpec(
        case_id="normalizes-uppercase-succeeded-statuses",
        description="normalize succeeded status casing before looking up badge colors",
        params=("SUCCEEDED",),
        expected="green",
    ),
    CaseSpec(
        case_id="returns-gray-for-unknown-statuses",
        description="return gray for unknown statuses",
        params=(" unknown ",),
        expected="gray",
    ),
    CaseSpec(
        case_id="returns-gray-for-unmapped-statuses-after-trimming",
        description="return gray for unmapped statuses after trimming whitespace",
        params=(" canceled ",),
        expected="gray",
    ),
)


if __name__ == "__main__":
    main()
