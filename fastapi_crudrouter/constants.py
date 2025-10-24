"""Constants and enumerations for CRUDRouter"""

from enum import Enum


class RouteType(str, Enum):
    """CRUD route types"""

    GET_ALL = "get_all"
    GET_ALL_OPTIONS = "get_all_options"
    GET_ONE = "get_one"
    CREATE = "create"
    UPDATE = "update"
    DELETE_ONE = "delete_one"
    DELETE_ALL = "delete_all"


class FilterOperator(str, Enum):
    """Filter operators"""

    EQUAL = "eq"
    GREATER_THAN_EQUAL = "gte"
    LESS_THAN_EQUAL = "lte"
    LIKE = "like"
    IN = "in"


# HTTP Status codes
HTTP_200_OK = 200
HTTP_201_CREATED = 201
HTTP_204_NO_CONTENT = 204
HTTP_404_NOT_FOUND = 404
HTTP_422_UNPROCESSABLE_ENTITY = 422

# Error messages
ERROR_NOT_FOUND = "Item not found"
ERROR_NO_PRIMARY_KEY = "Model {model} must have a primary key"
ERROR_NO_PERMISSION = "No permission to {action} resources"
