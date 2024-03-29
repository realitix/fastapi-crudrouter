from typing import Dict, TypeVar, Optional, Sequence, Any

from fastapi.params import Depends
from pydantic import BaseModel

PAGINATION = Dict[str, Any]
PYDANTIC_SCHEMA = BaseModel

T = TypeVar("T", bound=BaseModel)
DEPENDENCIES = Optional[Sequence[Depends]]
