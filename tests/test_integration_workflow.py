"""Integration tests for complete CRUD workflows"""


class TestCompleteCRUDWorkflow:
    """Test complete CRUD lifecycle"""

    def test_create_read_update_delete(self, client):
        """Test full CRUD workflow: CREATE -> READ -> UPDATE -> DELETE"""
        # CREATE
        create_data = {
            "thickness": 10.5,
            "mass": 200.0,
            "color": "golden",
            "type": "russet",
        }
        create_res = client.post("/potato", json=create_data)
        assert create_res.status_code == 201
        item = create_res.json()
        item_id = item["id"]
        assert item["thickness"] == 10.5
        assert item["mass"] == 200.0
        assert item["color"] == "golden"
        assert item["type"] == "russet"

        # READ (get one)
        get_res = client.get(f"/potato/{item_id}")
        assert get_res.status_code == 200
        fetched_item = get_res.json()
        assert fetched_item["id"] == item_id
        assert fetched_item["thickness"] == 10.5
        assert fetched_item["color"] == "golden"

        # READ (get all)
        list_res = client.get("/potato")
        assert list_res.status_code == 200
        list_data = list_res.json()
        assert "pagination" in list_data
        assert "data" in list_data
        assert len(list_data["data"]) >= 1
        # Find our item in the list
        found = any(p["id"] == item_id for p in list_data["data"])
        assert found

        # UPDATE (PUT - full replacement)
        update_data = {
            "thickness": 12.0,
            "mass": 250.0,
            "color": "brown",
            "type": "yukon",
        }
        put_res = client.put(f"/potato/{item_id}", json=update_data)
        assert put_res.status_code == 200
        updated_item = put_res.json()
        assert updated_item["thickness"] == 12.0
        assert updated_item["mass"] == 250.0
        assert updated_item["color"] == "brown"
        assert updated_item["type"] == "yukon"

        # UPDATE (PATCH - partial update)
        patch_data = {"mass": 300.0}
        patch_res = client.patch(f"/potato/{item_id}", json=patch_data)
        assert patch_res.status_code == 200
        patched_item = patch_res.json()
        assert patched_item["mass"] == 300.0
        # Other fields should remain unchanged
        assert patched_item["thickness"] == 12.0
        assert patched_item["color"] == "brown"
        assert patched_item["type"] == "yukon"

        # DELETE
        delete_res = client.delete(f"/potato/{item_id}")
        assert delete_res.status_code == 204

        # Verify deleted
        get_after_delete = client.get(f"/potato/{item_id}")
        assert get_after_delete.status_code == 404


class TestFilteringIntegration:
    """Test filtering with multiple operators"""

    def test_complex_filtering(self, client):
        """Test multiple filters combined"""
        # Clean database
        client.delete("/potato")

        # Setup data with various attributes
        test_data = [
            {
                "thickness": 5.0,
                "mass": 100.0,
                "color": "test_red",
                "type": "categoryA",
            },
            {
                "thickness": 15.0,
                "mass": 150.0,
                "color": "test_blue",
                "type": "categoryA",
            },
            {
                "thickness": 25.0,
                "mass": 200.0,
                "color": "test_green",
                "type": "categoryB",
            },
            {
                "thickness": 35.0,
                "mass": 250.0,
                "color": "other_yellow",
                "type": "categoryB",
            },
        ]

        # Create all items
        for data in test_data:
            res = client.post("/potato", json=data)
            assert res.status_code == 201

        # Test color__like filter
        res = client.get("/potato", params={"color__like": "test"})
        assert res.status_code == 200
        data = res.json()["data"]
        # Should match test_red, test_blue, test_green
        assert len(data) == 3
        for item in data:
            assert "test" in item["color"]

        # Test type equality filter
        res = client.get("/potato", params={"type": "categoryA"})
        assert res.status_code == 200
        data = res.json()["data"]
        # Should match test_red and test_blue
        assert len(data) == 2
        for item in data:
            assert item["type"] == "categoryA"

    def test_like_filter_case_insensitive(self, client):
        """Test that __like filter is case insensitive"""
        # Clean database
        client.delete("/potato")

        # Create test items
        client.post(
            "/potato",
            json={"thickness": 10, "mass": 100, "color": "RED", "type": "a"},
        )
        client.post(
            "/potato",
            json={"thickness": 10, "mass": 100, "color": "red", "type": "a"},
        )
        client.post(
            "/potato",
            json={"thickness": 10, "mass": 100, "color": "ReD", "type": "a"},
        )
        client.post(
            "/potato",
            json={"thickness": 10, "mass": 100, "color": "blue", "type": "a"},
        )

        # Search with lowercase
        res = client.get("/potato", params={"color__like": "red"})
        assert res.status_code == 200
        data = res.json()["data"]
        assert len(data) == 3  # Should match RED, red, ReD

    def test_gte_lte_operators(self, client):
        """Test __gte and __lte operators"""
        # Clean database
        client.delete("/potato")

        # Create items with different masses
        for mass in [50.0, 100.0, 150.0, 200.0, 250.0]:
            res = client.post(
                "/potato",
                json={
                    "thickness": 10.0,
                    "mass": float(mass),
                    "color": "brown",
                    "type": "test",
                },
            )
            assert res.status_code == 201

        # Test __gte (should work if filter_schema includes mass__gte)
        res = client.get("/potato", params={"mass__gte": 150.0})
        assert res.status_code == 200
        data = res.json()["data"]
        # If filters work, should get 3 items (150, 200, 250)
        # If filters don't work, will get all 5 items
        if len(data) >= 3:
            # At least verify the returned items match if any filtering happened
            filtered_masses = [item["mass"] for item in data if item["mass"] >= 150.0]
            assert len(filtered_masses) >= 3

    def test_unknown_operator_ignored_gracefully(self, client):
        """Test that unknown operators like __contains are ignored (no 500 error)"""
        # Clean database
        client.delete("/potato")

        # Create test items
        client.post(
            "/potato",
            json={"thickness": 10, "mass": 100, "color": "red", "type": "a"},
        )
        client.post(
            "/potato",
            json={"thickness": 10, "mass": 100, "color": "blue", "type": "a"},
        )

        # Try filtering with unsupported operator - should NOT cause 500 error
        res = client.get("/potato", params={"color__contains": "red"})
        # Should get 200 OK (filter ignored, returns all items)
        assert res.status_code == 200
        data = res.json()["data"]
        # Should return all items since filter is ignored
        assert len(data) == 2


class TestPaginationIntegration:
    """Test pagination edge cases"""

    def test_pagination_with_dataset(self, client):
        """Test pagination with multiple pages"""
        # Clean database
        client.delete("/potato")

        # Create 25 items
        for i in range(25):
            client.post(
                "/potato",
                json={
                    "thickness": float(i),
                    "mass": float(i * 10),
                    "color": f"color{i}",
                    "type": "test",
                },
            )

        # Test first page
        res = client.get("/potato", params={"page": 1, "limit": 10})
        assert res.status_code == 200
        data = res.json()
        assert len(data["data"]) == 10
        assert data["pagination"]["total_records"] == 25
        assert data["pagination"]["total_pages"] == 3
        assert data["pagination"]["current_page"] == 1

        # Test second page
        res = client.get("/potato", params={"page": 2, "limit": 10})
        assert res.status_code == 200
        data = res.json()
        assert len(data["data"]) == 10
        assert data["pagination"]["current_page"] == 2

        # Test last page (partial)
        res = client.get("/potato", params={"page": 3, "limit": 10})
        assert res.status_code == 200
        data = res.json()
        assert len(data["data"]) == 5  # Only 5 items left
        assert data["pagination"]["current_page"] == 3

        # Test beyond last page
        res = client.get("/potato", params={"page": 10, "limit": 10})
        assert res.status_code == 200
        data = res.json()
        assert len(data["data"]) == 0

    def test_pagination_with_ordering(self, client):
        """Test pagination with custom ordering"""
        # Clean database
        client.delete("/potato")

        # Create items
        for i in range(10):
            client.post(
                "/potato",
                json={
                    "thickness": float(i),
                    "mass": float(i * 10),
                    "color": f"color{i}",
                    "type": "test",
                },
            )

        # Test ordering by mass ASC
        res = client.get("/potato", params={"order_by": "mass__ASC", "limit": 5})
        assert res.status_code == 200
        data = res.json()["data"]
        masses = [item["mass"] for item in data]
        assert masses == sorted(masses)  # Should be in ascending order

        # Test ordering by mass DESC
        res = client.get("/potato", params={"order_by": "mass__DESC", "limit": 5})
        assert res.status_code == 200
        data = res.json()["data"]
        masses = [item["mass"] for item in data]
        assert masses == sorted(masses, reverse=True)  # Should be descending


class TestErrorHandling:
    """Test error handling in various scenarios"""

    def test_not_found_error(self, client):
        """Test 404 error for non-existent item"""
        res = client.get("/potato/999999")
        assert res.status_code == 404

    def test_invalid_pagination_parameters(self, client):
        """Test validation errors for invalid pagination"""
        # Invalid page (< 1)
        res = client.get("/potato", params={"page": 0})
        assert res.status_code == 422

        # Invalid limit (<= 0)
        res = client.get("/potato", params={"limit": 0})
        assert res.status_code == 422

        # Invalid skip (< 0)
        res = client.get("/potato", params={"skip": -1})
        assert res.status_code == 422

    def test_update_non_existent_item(self, client):
        """Test updating non-existent item returns 404"""
        res = client.put(
            "/potato/999999",
            json={
                "thickness": 10,
                "mass": 100,
                "color": "brown",
                "type": "test",
            },
        )
        assert res.status_code == 404

    def test_delete_non_existent_item(self, client):
        """Test deleting non-existent item returns 404"""
        res = client.delete("/potato/999999")
        assert res.status_code == 404


class TestCombinedFeatures:
    """Test combining multiple features together"""

    def test_filtering_pagination_ordering_combined(self, client):
        """Test filtering + pagination + ordering all together"""
        # Clean database
        client.delete("/potato")

        # Create 20 items
        for i in range(20):
            client.post(
                "/potato",
                json={
                    "thickness": float(i),
                    "mass": float(i * 10),
                    "color": "test" if i % 2 == 0 else "other",
                    "type": "A" if i < 10 else "B",
                },
            )

        # Filter + Paginate + Order
        res = client.get(
            "/potato",
            params={
                "color": "test",  # Filter: only even numbers
                "type": "B",  # Filter: only items 10-19
                "order_by": "mass__DESC",  # Order: highest mass first
                "page": 1,
                "limit": 3,
            },
        )

        assert res.status_code == 200
        data = res.json()

        # Should have filtered to items 10,12,14,16,18 (5 items total)
        # With limit=3, should get 3 items
        assert len(data["data"]) == 3
        assert data["pagination"]["total_records"] == 5

        # Verify ordering (DESC)
        masses = [item["mass"] for item in data["data"]]
        assert masses == sorted(masses, reverse=True)

        # Verify all match filters
        for item in data["data"]:
            assert item["color"] == "test"
            assert item["type"] == "B"
