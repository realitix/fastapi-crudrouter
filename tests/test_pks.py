from . import test_router

potato_type = {"name": "russet", "origin": "Canada"}
URL = "/potato_type"


def test_get(string_pk_client):
    test_router.test_get(string_pk_client, URL)


def test_post(string_pk_client):
    test_router.test_post(string_pk_client, URL, potato_type)


def test_get_one(string_pk_client):
    test_router.test_get_one(
        string_pk_client, URL, {"name": "kenebec", "origin": "Ireland"}, "name"
    )


def test_delete_one(string_pk_client):
    test_router.test_delete_one(
        string_pk_client, URL, {"name": "golden", "origin": "Ireland"}, "name"
    )


def test_delete_all(string_pk_client):
    test_router.test_delete_all(
        string_pk_client,
        URL,
        {"name": "red", "origin": "Ireland"},
        {"name": "brown", "origin": "Ireland"},
    )
