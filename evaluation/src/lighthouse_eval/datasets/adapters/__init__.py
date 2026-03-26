from .base import DatasetAdapter

ADAPTERS: dict[str, type[DatasetAdapter]] = {}
"""Adapter registry. Populated by adapter modules as they are imported."""


def register(name: str):
    """Class decorator that registers an adapter under *name*."""

    def _wrap(cls: type[DatasetAdapter]):
        ADAPTERS[name] = cls
        return cls

    return _wrap


def get_adapter(name: str) -> type[DatasetAdapter]:
    if name not in ADAPTERS:
        raise KeyError(
            f"Unknown dataset adapter {name!r}. "
            f"Available: {sorted(ADAPTERS)}"
        )
    return ADAPTERS[name]


# Auto-import adapters so they register themselves.
from . import custom as _custom  # noqa: E402, F401
from . import swebench as _swebench  # noqa: E402, F401
from . import bugsinpy as _bugsinpy  # noqa: E402, F401
from . import pybughive as _pybughive  # noqa: E402, F401
from . import crosscodeeval as _crosscodeeval  # noqa: E402, F401
from . import repobench as _repobench  # noqa: E402, F401
from . import repoqa as _repoqa  # noqa: E402, F401

__all__ = ["ADAPTERS", "DatasetAdapter", "get_adapter", "register"]
