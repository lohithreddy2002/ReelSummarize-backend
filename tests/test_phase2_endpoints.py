import unittest

from fastapi.testclient import TestClient

import composition_root
import main as main_module
from adapters.persistence.in_memory import InMemoryPersistenceAdapter
from domain.models import ExtractedMenuItem, Location


class Phase2EndpointTests(unittest.TestCase):
    def setUp(self):
        composition_root._persistence_singleton = None
        composition_root._storage_singleton = None
        main_module.content_service = main_module.ContentService(composition_root.get_persistence())
        main_module.collections_service = main_module.CollectionsService(composition_root.get_persistence())
        main_module.search_service = main_module.SearchService(composition_root.get_persistence())
        main_module.suggestions_service = main_module.SuggestionsService(composition_root.get_persistence())
        self.client = TestClient(main_module.app)

    def test_collections_search_suggestions_auth(self):
        p = composition_root.get_persistence()
        assert isinstance(p, InMemoryPersistenceAdapter)

        # Seed content for u1
        import asyncio

        async def seed():
            c1 = await p.create_content("u1", "https://www.instagram.com/reel/a/")
            await p.update_content(
                c1.id,
                "u1",
                status="ready",
                title_generated="Coffee in Paris",
                summary_text="A morning cafe tour",
                semantic_tags=["cafe", "travel"],
            )
            c2 = await p.create_content("u1", "https://www.instagram.com/reel/b/")
            await p.update_content(
                c2.id,
                "u1",
                status="ready",
                title_generated="Beach sunset",
                summary_text="Waves and sand",
            )
            await p.add_bookmark("u1", c1.id)
            col = await p.create_collection("u1", "Favorites", None, "custom", None)
            await p.add_collection_item(col.id, "u1", c1.id)
            p.seed_menu_items(
                c1.id,
                [
                    ExtractedMenuItem(
                        name="Latte",
                        item_type="drink",
                        price_display="$4",
                        price_confidence=0.9,
                    )
                ],
            )

        asyncio.run(seed())

        r = self.client.get("/api/search", headers={"x-user-id": "u1"}, params={"q": "coffee"})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["success"])
        self.assertGreaterEqual(data["count"], 1)

        r2 = self.client.get("/api/search", headers={"x-user-id": "u1"}, params={"smart": "to_visit"})
        self.assertEqual(r2.status_code, 200)
        self.assertGreaterEqual(r2.json()["count"], 1)

        r3 = self.client.get("/api/suggestions", headers={"x-user-id": "u1"})
        self.assertEqual(r3.status_code, 200)
        self.assertIn("tags", r3.json())

        rc = self.client.get("/api/collections", headers={"x-user-id": "u1"})
        self.assertEqual(rc.status_code, 200)
        self.assertEqual(rc.json()["count"], 1)

        col_id = rc.json()["items"][0]["id"]
        ri = self.client.get(f"/api/collections/{col_id}/items", headers={"x-user-id": "u1"})
        self.assertEqual(ri.status_code, 200)
        self.assertEqual(ri.json()["count"], 1)

        # u2 cannot read u1 collection items
        self.assertEqual(
            self.client.get(f"/api/collections/{col_id}/items", headers={"x-user-id": "u2"}).json()["count"],
            0,
        )

    def test_content_detail_menu_and_map_enrichment(self):
        p = composition_root.get_persistence()
        assert isinstance(p, InMemoryPersistenceAdapter)

        import asyncio

        async def seed():
            c = await p.create_content("u1", "https://www.instagram.com/reel/x/")
            await p.update_content(
                c.id,
                "u1",
                status="ready",
                title_generated="Test",
                summary_text="Body",
                curator_insight="Nice spot",
            )
            await p.upsert_locations(
                c.id,
                [
                    Location(
                        name="Spot",
                        lat=1.0,
                        lng=2.0,
                        geocoded=True,
                        rating=4.5,
                        review_count=120,
                        place_category="cafe",
                        image_url="https://example.com/p.jpg",
                    )
                ],
            )
            p.seed_menu_items(
                c.id,
                [ExtractedMenuItem(name="Espresso", item_type="drink", price_display="$3")],
            )
            return c.id

        cid = asyncio.run(seed())

        d = self.client.get(f"/api/content/{cid}", headers={"x-user-id": "u1"})
        self.assertEqual(d.status_code, 200)
        body = d.json()
        self.assertEqual(body["content"]["curator_insight"], "Nice spot")
        self.assertIsNotNone(body.get("menu_items"))
        self.assertEqual(len(body["menu_items"]), 1)
        self.assertEqual(body["menu_items"][0]["name"], "Espresso")
        self.assertIsNotNone(body.get("locations"))
        self.assertEqual(len(body["locations"]), 1)
        self.assertEqual(body["locations"][0]["name"], "Spot")
        self.assertTrue(body["locations"][0]["geocoded"])

        m = self.client.get("/api/map/locations", headers={"x-user-id": "u1"})
        self.assertEqual(m.status_code, 200)
        pts = m.json()["points"]
        self.assertEqual(len(pts), 1)
        self.assertEqual(pts[0]["rating"], 4.5)
        self.assertEqual(pts[0]["review_count"], 120)
        self.assertEqual(pts[0]["place_category"], "cafe")


if __name__ == "__main__":
    unittest.main()
