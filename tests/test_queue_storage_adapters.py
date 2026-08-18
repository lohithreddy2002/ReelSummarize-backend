import unittest

from adapters.storage.in_memory import InMemoryStorageAdapter


class StorageAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_in_memory_storage_put_and_sign(self):
        s = InMemoryStorageAdapter()
        path = await s.put_object("a/b.txt", b"hello", "text/plain")
        url = await s.get_signed_url(path, 60)
        self.assertIn("memory://", url)
        await s.delete_object(path)


if __name__ == "__main__":
    unittest.main()
