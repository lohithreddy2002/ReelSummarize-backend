import unittest

from adapters.persistence.in_memory import InMemoryPersistenceAdapter
from tests.fixtures.phase1_seed import seed_sample_content


class Phase1SeedFixtureTests(unittest.IsolatedAsyncioTestCase):
    async def test_seed_populates_feed_and_map(self):
        persistence = InMemoryPersistenceAdapter()
        content_id, _job_id = await seed_sample_content(persistence, owner_user_id="u_seed")
        feed = await persistence.list_feed("u_seed", 10, 0)
        self.assertEqual(len(feed), 1)
        self.assertEqual(feed[0].id, content_id)
        points = await persistence.list_map_locations("u_seed")
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0].name, "Mumbai")


if __name__ == "__main__":
    unittest.main()
