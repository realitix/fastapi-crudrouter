from pytest import mark

from tests import CUSTOM_TAGS

POTATO_TAGS = ["Potato"]
PATHS = ["/potato", "/carrot"]
PATH_TAGS = {
    "/potato": POTATO_TAGS,
    "/potato/{item_id}": POTATO_TAGS,
    "/carrot": CUSTOM_TAGS,
    "/carrot/{item_id}": CUSTOM_TAGS,
}


class TestOpenAPISpec:
    def _get_schema(self, client):
        res = client.get("/openapi.json")
        assert res.status_code == 200
        return res

    def test_schema_exists(self, client):
        self._get_schema(client)

    def test_schema_tags(self, client):
        schema = self._get_schema(client).json()
        paths = schema["paths"]

        assert len(paths) == len(PATH_TAGS)
        for path, method in paths.items():
            # Root paths have 4 methods (GET, OPTIONS, POST, DELETE)
            # Item paths have 4 methods (GET, PUT, PATCH, DELETE)
            expected_methods = 4
            assert len(method) == expected_methods

            for m in method:
                assert method[m]["tags"] == PATH_TAGS[path]

    @mark.parametrize("path", PATHS)
    def test_response_types(self, client, path):
        schema = self._get_schema(client).json()
        paths = schema["paths"]

        # GET returns 200
        assert "200" in paths[path]["get"]["responses"]
        # POST returns 201
        assert "201" in paths[path]["post"]["responses"]
        # DELETE ALL returns 200 (with empty list in pagination format)
        assert "200" in paths[path]["delete"]["responses"]

        assert "422" in paths[path]["post"]["responses"]

        item_path = path + "/{item_id}"
        # GET and PUT return 200
        for method in ["get", "put"]:
            assert "200" in paths[item_path][method]["responses"]
            assert "404" in paths[item_path][method]["responses"]
            assert "422" in paths[item_path][method]["responses"]

        # DELETE ONE returns 204 (No Content)
        assert "204" in paths[item_path]["delete"]["responses"]
        assert "404" in paths[item_path]["delete"]["responses"]
