# pylint: disable=useless-import-alias
from pydantic import BaseModel, ConfigDict

from .conf import config as config

PAGINATION_SIZE = 10
CUSTOM_TAGS = ["Tag1", "Tag2"]


class ORMModel(BaseModel):
    id: int

    model_config = ConfigDict(from_attributes=True)


class PotatoCreate(BaseModel):
    thickness: float
    mass: float
    color: str
    type: str


class Potato(PotatoCreate, ORMModel):
    pass


class CustomPotato(PotatoCreate):
    potato_id: int

    model_config = ConfigDict(from_attributes=True)


class CarrotCreate(BaseModel):
    length: float
    color: str = "Orange"


class CarrotUpdate(BaseModel):
    length: float


class Carrot(CarrotCreate, ORMModel):
    pass


class PotatoType(BaseModel):
    name: str
    origin: str

    model_config = ConfigDict(from_attributes=True)
