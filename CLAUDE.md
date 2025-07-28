# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Testing
- `pytest` - Run all tests
- `pytest tests/test_specific.py` - Run specific test file
- `pytest -k "test_name"` - Run tests matching pattern
- `pytest --verbose` - Run tests with verbose output

### Code Quality
- `flake8` - Run linting (configured in setup.cfg)
- `mypy fastapi_crudrouter/` - Run type checking (strict mode enabled)

### Development Environment
- Install development dependencies: `pip install -r tests/dev.requirements.txt`
- The project requires Python 3.7+ and supports up to Python 3.11
- Core dependencies: `fastapi>=0.62.0`, `sqlalchemy[asyncio]`

## Architecture Overview

This is a simplified FastAPI extension library that automatically generates CRUD routes for Pydantic models using SQLAlchemy async exclusively.

### Core Architecture
- **Main Router**: `fastapi_crudrouter/crud_router.py` contains the `CRUDRouter` class
- **Single Backend**: SQLAlchemy async only - no more abstraction layers
- **Route Generation**: Automatically creates 6 standard CRUD routes (get_all, get_one, create, update, delete_one, delete_all)
- **Schema Management**: Built-in dynamic schema generation for create/update operations

### Key Features Preserved
- **Advanced Pagination**: Full pagination with metadata (total_records, total_pages, current_page)
- **Complex Filtering**: Support for `__gte`, `__lte`, `__like` operators
- **Joins and Relations**: Support for join_fields and join_list_fields
- **Custom Functions**: Custom query functions via custom_func_fields
- **Dynamic Sorting**: Support for ASC/DESC ordering
- **Schema Customization**: Custom create, update, and get_all schemas
- **Primary Key Support**: Custom primary key field names and types
- **Integrity Handling**: Automatic rollback on database errors

### Simplified Structure
- **No Abstraction**: Direct SQLAlchemy async implementation without abstract base classes
- **Single File**: All functionality in `crud_router.py`
- **Backward Compatibility**: `SQLAlchemyCRUDRouter` alias for existing code
- **Clean Dependencies**: Only SQLAlchemy and FastAPI dependencies

### Testing Structure
- **Single Implementation**: Only SQLAlchemy async tests in `tests/implementations/sqlalchemy_.py`
- **Async Wrappers**: Sync wrapper functions for backward compatibility with existing tests
- **Simplified Fixtures**: Only SQLAlchemy-specific test fixtures

### Code Style Guidelines
- Maximum line length: 88 characters (flake8)
- Strict mypy typing enforced (except for tests)
- Import order: PyCharm style
- Type annotations required for all function definitions

### Usage Patterns
- Import `CRUDRouter` or `SQLAlchemyCRUDRouter` (alias) from the main package
- Provide Pydantic schema, SQLAlchemy model, and async session generator
- All routes are async by default
- Schema customization through optional create_schema, update_schema, etc.
- Filtering via optional filter_schema with automatic operator support
- Primary key customization via the model's primary key configuration

### Package Structure
- Main router in `crud_router.py`
- Main exports in `__init__.py`: `CRUDRouter` and `SQLAlchemyCRUDRouter` (alias)
- Version management in `_version.py`
- All utility functions integrated into the main router class