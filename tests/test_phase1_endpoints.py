import unittest

from fastapi.testclient import TestClient

import composition_root
import main as main_module


class Phase1EndpointTests(unittest.TestCase):
    def setUp(self):
        # Ensure a clean in-memory app state per test.
        composition_root._persistence_singleton = None
        composition_root._storage_singleton = None
        main_module.content_service = main_module.ContentService(composition_root.get_persistence())
        self.client = TestClient(main_module.app)

    def test_content_crud_feed_status_bookmark_and_ownership(self):
        # Avoid external calls during endpoint test.
        async def _fake_enrich(owner_user_id: str, content_id: str):
            _ = owner_user_id
            _ = content_id
            return None

        original_enrich = main_module.content_service.enrich_content_now
        main_module.content_service.enrich_content_now = _fake_enrich
        try:
            create_resp = self.client.post(
                "/api/content",
                headers={"x-user-id": "u1"},
                json={"source_url": "https://www.instagram.com/reel/test123"},
            )
            self.assertEqual(create_resp.status_code, 200)
            create_data = create_resp.json()
            content_id = create_data["content"]["id"]
            self.assertEqual(create_data["status"]["content_id"], content_id)

            detail_resp = self.client.get(f"/api/content/{content_id}", headers={"x-user-id": "u1"})
            self.assertEqual(detail_resp.status_code, 200)

            status_resp = self.client.get(f"/api/content/{content_id}/status", headers={"x-user-id": "u1"})
            self.assertEqual(status_resp.status_code, 200)
            self.assertEqual(status_resp.json()["success"], True)

            feed_resp = self.client.get("/api/feed", headers={"x-user-id": "u1"})
            self.assertEqual(feed_resp.status_code, 200)
            self.assertEqual(feed_resp.json()["count"], 1)

            map_resp = self.client.get("/api/map/locations", headers={"x-user-id": "u1"})
            self.assertEqual(map_resp.status_code, 200)
            self.assertIn("points", map_resp.json())

            bookmark_resp = self.client.post(f"/api/content/{content_id}/bookmark", headers={"x-user-id": "u1"})
            self.assertEqual(bookmark_resp.status_code, 200)
            self.assertEqual(bookmark_resp.json()["content_id"], content_id)

            # Ownership: different user should not read detail, feed, map, status, or bookmark.
            self.assertEqual(
                self.client.get(f"/api/content/{content_id}", headers={"x-user-id": "u2"}).status_code,
                404,
            )
            self.assertEqual(self.client.get("/api/feed", headers={"x-user-id": "u2"}).json()["count"], 0)
            self.assertEqual(
                self.client.get(f"/api/content/{content_id}/status", headers={"x-user-id": "u2"}).json()[
                    "content_status"
                ],
                "not_found",
            )
            self.assertEqual(self.client.get("/api/map/locations", headers={"x-user-id": "u2"}).json()["count"], 0)
            self.assertEqual(
                self.client.post(
                    f"/api/content/{content_id}/bookmark", headers={"x-user-id": "u2"}
                ).status_code,
                404,
            )
        finally:
            main_module.content_service.enrich_content_now = original_enrich


if __name__ == "__main__":
    unittest.main()
