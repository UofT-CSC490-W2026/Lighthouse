from __future__ import annotations


def snake_to_camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(w.capitalize() for w in parts[1:])


def flatten_dict(d: dict, parent_key: str = "", sep: str = ".") -> dict[str, object]:
    items: list[tuple[str, object]] = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def unique_sorted(items: list) -> list:
    return sorted(set(items))
