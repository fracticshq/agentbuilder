"""Security package exports without eager authentication imports.

Submodules such as malware scanning are used by core services during API
bootstrap.  Importing rate limiting eagerly here would pull authentication
dependencies back into that bootstrap path and create a circular import.
Keep the historical package-level exports, but resolve them only when callers
actually request them.
"""

from importlib import import_module
from typing import Any

__all__ = [
    "RateLimiter",
    "rate_limit_dependency",
    "check_rate_limit",
    "check_named_rate_limit",
    "check_permission",
    "check_brand_access",
]


def __getattr__(name: str) -> Any:
    if name in {"RateLimiter", "rate_limit_dependency", "check_rate_limit", "check_named_rate_limit"}:
        return getattr(import_module(".rate_limiter", __name__), name)
    if name in {"check_permission", "check_brand_access"}:
        return getattr(import_module(".rbac", __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
