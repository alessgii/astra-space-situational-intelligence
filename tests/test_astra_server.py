import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from astra_server import app


class AstraServerTests(unittest.TestCase):
    client = TestClient(app)

    def test_health_endpoint(self):
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"status": "ok", "service": "astra-api"}
        )

    def test_chat_receives_and_classifies_solar_question(self):
        response = self.client.post(
            "/api/chat",
            json={
                "message": "¿Habrá alguna llamarada solar en los próximos 3 días?",
                "location": {"latitude": 19.43, "longitude": -99.13},
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "accepted")
        self.assertEqual(body["intent"]["domain"], "space_weather")
        self.assertEqual(
            body["intent"]["suggested_tool"], "get_space_weather"
        )
        self.assertEqual(body["next_action"], "configure_watsonx_credentials")

    def test_chat_rejects_blank_message(self):
        response = self.client.post("/api/chat", json={"message": "   "})

        self.assertEqual(response.status_code, 422)

    def test_chat_marks_unrecognized_question_for_clarification(self):
        response = self.client.post(
            "/api/chat", json={"message": "Cuéntame algo interesante"}
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["intent"]["domain"], "unknown")
        self.assertEqual(body["next_action"], "configure_watsonx_credentials")

    @patch("astra_server.watsonx_is_configured", return_value=True)
    @patch("astra_server.run_watsonx_agent", new_callable=AsyncMock)
    def test_chat_returns_final_agent_answer(self, agent_mock, configured_mock):
        agent_mock.return_value = (
            "NASA registró dos llamaradas; estos datos no son un pronóstico.",
            "get_space_weather",
            {"source": "NASA DONKI", "event_count": 2},
        )

        response = self.client.post(
            "/api/chat",
            json={"message": "¿Habrá llamaradas solares en los próximos días?"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["tool_used"], "get_space_weather")
        self.assertEqual(body["tool_result"]["event_count"], 2)
        self.assertEqual(body["next_action"], "none")

    @patch("astra_server.fetch_donki_flares", new_callable=AsyncMock)
    def test_solar_flares_returns_compact_observed_data(self, fetch_mock):
        fetch_mock.return_value = [
            {
                "flrID": "2026-08-24T12:00:00-FLR-001",
                "beginTime": "2026-08-24T12:00:00Z",
                "peakTime": "2026-08-24T12:08:00Z",
                "endTime": "2026-08-24T12:20:00Z",
                "classType": "M2.4",
                "sourceLocation": "N12W30",
                "activeRegionNum": 14501,
                "link": "https://example.test/flare",
                "instruments": [{"displayName": "field intentionally removed"}],
            },
            {
                "flrID": "2026-08-25T08:00:00-FLR-001",
                "beginTime": "2026-08-25T08:00:00Z",
                "classType": "X1.1",
            },
        ]

        response = self.client.get("/api/space-weather/solar-flares?days=3")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["observed_events_only"])
        self.assertEqual(body["event_count"], 2)
        self.assertEqual(body["strongest_class"], "X1.1")
        self.assertEqual(body["events"][0]["class_type"], "X1.1")
        self.assertNotIn("instruments", body["events"][1])

    def test_solar_flares_rejects_ranges_longer_than_30_days(self):
        response = self.client.get("/api/space-weather/solar-flares?days=31")

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
