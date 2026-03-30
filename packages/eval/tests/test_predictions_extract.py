from __future__ import annotations

import pytest

from eval.predictions import extract_model_patch


@pytest.mark.unit
def test_extract_model_patch_normalizes_path_only_diff_headers() -> None:
    raw = """```diff
a/consumer_app/tags.py
b/consumer_app/tags.py
index 1234567..89abcde 100644
--- a/consumer_app/tags.py
+++ b/consumer_app/tags.py
@@ -1 +1 @@
-old
+new
```"""

    patch = extract_model_patch(raw)

    assert patch.startswith("diff --git a/consumer_app/tags.py b/consumer_app/tags.py\n")
    assert "<diff>" not in patch
    assert "@@ -1,1 +1,1 @@" in patch


@pytest.mark.unit
def test_extract_model_patch_removes_diff_placeholders() -> None:
    raw = """```diff
--- a/consumer_app/statuses.py
+++ b/consumer_app/statuses.py
@@ -1 +1 @@
<diff>
-old
+new
```"""

    patch = extract_model_patch(raw)

    assert "<diff>" not in patch


@pytest.mark.unit
def test_extract_model_patch_recalculates_hunk_counts() -> None:
    raw = """```diff
--- a/consumer_app/tags.py
+++ b/consumer_app/tags.py
@@ -6,7 +6,7 @@ def normalized_tag_line(tags: list[str]) -> str:
     normalized_tags = normalize_tags(tags)
     # Remove duplicates while preserving order
     seen = set()
-    unique_tags = [tag for tag in sorted(normalized_tags) if not (tag in seen or seen.add(tag))]
+    unique_tags = [tag for tag in normalized_tags if not (tag in seen or seen.add(tag))]
     return ", ".join(unique_tags)
```"""

    patch = extract_model_patch(raw)

    assert "@@ -6,5 +6,5 @@ def normalized_tag_line(tags: list[str]) -> str:" in patch


@pytest.mark.unit
def test_extract_model_patch_prefixes_missing_context_markers() -> None:
    raw = """```diff
--- a/consumer_app/tags.py
+++ b/consumer_app/tags.py
@@ -5,3 +5,3 @@ from providerlib.identity import normalize_tags

 def normalized_tag_line(tags: list[str]) -> str:
     normalized = normalize_tags(tags)
-    return ", ".join(sorted(normalized))
+    return ", ".join(normalized)
```"""

    patch = extract_model_patch(raw)

    assert "@@ -5,4 +5,4 @@ from providerlib.identity import normalize_tags" in patch
    assert "\n \n def normalized_tag_line(tags: list[str]) -> str:\n" in patch
    assert "\n     normalized = normalize_tags(tags)\n" in patch
