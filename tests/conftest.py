from fastapi.testclient import TestClient
import pytest

from .implementations import (
    implementations,
    sqlalchemy_implementation_custom_ids,
    sqlalchemy_implementation_string_pk,
    sqlalchemy_implementation_integrity_errors,
)


def yield_test_client(app, impl):
    with TestClient(app) as c:
        yield c


def label_func(*args):
    func, dsn = args[0]
    dsn = dsn.split(":")[0].split("+")[0]
    return f"{func.__name__}-{dsn}"


@pytest.fixture(params=implementations, ids=label_func, scope="class")
def client(request):
    impl, dsn = request.param

    app, router, settings = impl(db_uri=dsn)
    [app.include_router(router(**kwargs)) for kwargs in settings]
    yield from yield_test_client(app, impl)


@pytest.fixture(
    params=[
        sqlalchemy_implementation_custom_ids,
    ]
)
def custom_id_client(request):
    yield from yield_test_client(request.param(), request.param)


@pytest.fixture(
    params=[
        sqlalchemy_implementation_string_pk,
    ],
    scope="function",
)
def string_pk_client(request):
    yield from yield_test_client(request.param(), request.param)


@pytest.fixture(
    params=[
        sqlalchemy_implementation_integrity_errors,
    ],
    scope="function",
)
def integrity_errors_client(request):
    yield from yield_test_client(request.param(), request.param)
