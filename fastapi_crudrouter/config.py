"""Configuration for CRUDRouter"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CRUDConfig:
    """Configuration for CRUDRouter behavior"""

    # Pagination
    default_page_size: int = 50
    max_page_size: Optional[int] = 1000

    # Performance
    enable_query_logging: bool = False
    use_eager_loading: bool = True
    batch_subdata_queries: bool = True

    # Security
    require_authentication: bool = False
    strict_permissions: bool = True

    # Features
    enable_delete_all: bool = False
    enable_options_route: bool = True

    # Error handling
    expose_sql_errors: bool = False
    custom_error_responses: dict = field(default_factory=dict)


# Global default config
default_config = CRUDConfig()


def set_default_config(config: CRUDConfig) -> None:
    """Set global default configuration"""
    global default_config  # pylint: disable=global-statement  # noqa: PLW0603
    default_config = config
