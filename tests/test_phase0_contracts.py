import unittest

from fastapi.testclient import TestClient

import main as main_module


class Phase0ContractTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main_module.app)

    def test_health_contract_and_request_id_header(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("status", data)
        self.assertIn("version", data)
        self.assertIn("gemini_configured", data)
        self.assertTrue(resp.headers.get("x-request-id"))

    def test_api_v1_alias_route_available(self):
        resp = self.client.get("/api/v1/feed", headers={"x-user-id": "u1"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("success", data)
        self.assertIn("items", data)

    def test_standard_error_envelope_for_http_exception(self):
        resp = self.client.get("/api/content/not-found-id", headers={"x-user-id": "u1"})
        self.assertEqual(resp.status_code, 404)
        data = resp.json()
        self.assertEqual(data["success"], False)
        self.assertIn("error", data)
        self.assertIn("code", data["error"])
        self.assertIn("message", data["error"])
        self.assertIn("retryable", data["error"])
        self.assertIn("request_id", data["error"])

    def test_metrics_endpoint_contract(self):
        resp = self.client.get("/api/metrics")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["success"], True)
        self.assertIn("metrics", data)


if __name__ == "__main__":
    unittest.main()
