from __future__ import annotations


def build_cache_key(namespace: str, identifier: str, *, version: str = "v1") -> str:
    """Build a normalized cache key."""
    normalized_namespace = namespace.strip().lower()
    normalized_identifier = identifier.strip().lower()
    if not normalized_namespace or not normalized_identifier:
        raise ValueError("namespace and identifier must not be empty")
    return f"{normalized_namespace}:{normalized_identifier}:{version}"
