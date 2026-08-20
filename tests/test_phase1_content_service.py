import unittest

from adapters.persistence.in_memory import InMemoryPersistenceAdapter
from application.content_service import ContentService
import application.content_service as content_service_module


class _FakeSummarizer:
    async def summarize(self, video_path=None, metadata=None, prefer_video=True):
        return {
            "success": True,
            "summary": "### Title:\nWeekend Food Crawl\n\n### 📍 Locations:\nMumbai, India",
            "method": "metadata_analysis",
            "summary_prompt_json": {
                "system_instruction": "test-system",
                "user_prompt": "test-user-prompt",
            },
        }


class _FakeLocation:
    def __init__(self, name, latitude, longitude, display_name):
        self.name = name
        self.latitude = latitude
        self.longitude = longitude
        self.display_name = display_name


class _FakeGeocoder:
    def extract_locations_from_text(self, _text):
        return ["Mumbai, India"]

    async def geocode_multiple(self, _names):
        return [_FakeLocation("Mumbai, India", 19.0760, 72.8777, "Mumbai, Maharashtra, India")]

    async def geocode_many_preserve_names(self, names):
        from services.geocoder import Location as GLoc

        return [(n, GLoc(n, 19.0760, 72.8777, "Mumbai, Maharashtra, India")) for n in names]


class Phase1ContentServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.persistence = InMemoryPersistenceAdapter()
        self.service = ContentService(self.persistence)

        self._orig_downloader = content_service_module.downloader
        self._orig_get_summarizer = content_service_module.get_summarizer
        self._orig_geocoder = content_service_module.geocoder

        class _FakeDownloader:
            async def download_media(self, _url):
                return {
                    "title": "Original reel title",
                    "thumbnail": "https://example.com/thumb.jpg",
                    "like_count": 12,
                    "comment_count": 2,
                    "view_count": 150,
                    "file_path": None,
                    "request_id": None,
                }

            def cleanup(self, _request_id):
                pass

        content_service_module.downloader = _FakeDownloader()
        content_service_module.get_summarizer = lambda: _FakeSummarizer()
        content_service_module.geocoder = _FakeGeocoder()

    async def asyncTearDown(self):
        content_service_module.downloader = self._orig_downloader
        content_service_module.get_summarizer = self._orig_get_summarizer
        content_service_module.geocoder = self._orig_geocoder

    async def test_content_lifecycle_and_feed_map(self):
        created = await self.service.ingest_content("u1", "https://www.instagram.com/reel/abc")
        content_id = created["content"].id

        await self.service.enrich_content_now("u1", content_id)
        status = await self.service.get_status("u1", content_id)

        self.assertIsNotNone(status)
        content = status["content"]
        job = status["job"]
        self.assertEqual(content.status, "ready")
        self.assertEqual(job.status, "completed")
        self.assertEqual(content.summary_method, "metadata_analysis")
        self.assertEqual(content.likes_count, 12)
        self.assertEqual(
            content.summary_prompt_json,
            {"system_instruction": "test-system", "user_prompt": "test-user-prompt"},
        )

        feed = await self.service.get_feed("u1", limit=10, offset=0)
        self.assertEqual(len(feed), 1)

        map_points = await self.service.get_map_locations("u1")
        self.assertEqual(len(map_points), 1)
        self.assertEqual(map_points[0].name, "Mumbai, India")
        self.assertTrue(map_points[0].geocoded)
        self.assertIsNotNone(map_points[0].lat)
        self.assertIsNotNone(map_points[0].lng)

        bookmarked = await self.service.bookmark("u1", content_id)
        self.assertTrue(bookmarked)


if __name__ == "__main__":
    unittest.main()
