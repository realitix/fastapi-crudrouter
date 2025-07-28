from ._version import __version__  # noqa: F401
from .core import (
    CRUDRouter,
    SQLAlchemyCRUDRouter,
)

__all__ = [
    "CRUDRouter",
    "SQLAlchemyCRUDRouter",
]
