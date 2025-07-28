# Backward compatibility module
# This module provides compatibility for projects that import from fastapi_crudrouter.core

from .crud_router import CRUDRouter

# Re-export with legacy names for backward compatibility
SQLAlchemyCRUDRouter = CRUDRouter
