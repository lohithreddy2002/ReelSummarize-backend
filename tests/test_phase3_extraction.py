"""Phase 3: persistence lookups, active extractions API."""

import unittest

import composition_root
import main as main_module
from adapters.persistence.in_memory import InMemoryPersistenceAdapter


class Phase3ExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        composition_root._persistence_singleton = None
        composition_root._storage_singleton = None
        main_module.content_service = main_module.ContentService(composition_root.get_persistence())
        self.client = __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(main_module.app)

    def tearDown(self) -> None:
        self.client.close()

    async def test_get_content_by_id(self) -> None:
        p = composition_root.get_persistence()
        assert isinstance(p, InMemoryPersistenceAdapter)
        c = await p.create_content("u1", "https://www.instagram.com/reel/byid/")
        got = await p.get_content_by_id(c.id)
        self.assertIsNotNone(got)
        assert got is not None
        self.assertEqual(got.owner_user_id, "u1")

    def test_active_extractions_endpoint_empty(self) -> None:
        r = self.client.get("/api/extractions/active", headers={"x-user-id": "u9"})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["items"], [])


if __name__ == "__main__":
    unittest.main()
