from __future__ import annotations


def build_url(scheme: str, host: str, path: str = "", query: dict[str, str] | None = None) -> str:
    url = f"{scheme}://{host}{path}"
    if query:
        pairs = "&".join(f"{k}={v}" for k, v in query.items())
        url += f"?{pairs}"
    return url


def build_csv_row(fields: list[str], delimiter: str = ",") -> str:
    escaped = []
    for f in fields:
        if delimiter in f:
            escaped.append(f'"{f}"')
        else:
            escaped.append(f)
    return delimiter.join(escaped)


def build_header(name: str, value: str) -> str:
    return f"{name.strip()}: {value.strip()}"
