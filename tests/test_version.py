def test_version():
    import fastapi_crudrouter  # noqa: PLC0415 pylint: disable=import-outside-toplevel

    assert isinstance(fastapi_crudrouter.__version__, str)


def test_version_file():
    from fastapi_crudrouter import (  # noqa: PLC0415 pylint: disable=import-outside-toplevel
        _version,
    )

    assert isinstance(_version.__version__, str)
