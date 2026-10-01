import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import requests

from gis_pipeline import (
    ArcGISClient,
    ArcGISConnectionError,
    ArcGISServiceError,
    ArcGISTimeoutError,
    ReferenceMarkerService,
)
from tests.test_reference_marker_service import arcgis_response, feature, layer_body


class FastRetryClient(ArcGISClient):
    """ArcGISClient with short timeouts so real-network tests run quickly."""
    SERVICE_NAME = "test service"
    CONNECT_TIMEOUT_SECONDS = 1
    READ_TIMEOUT_SECONDS = 0.3
    RETRY_BACKOFF_SECONDS = 0


@patch("gis_pipeline.time.sleep")  # skip retry backoff delays
@patch("gis_pipeline.requests.Session.get")
class RetryTests(unittest.TestCase):
    def setUp(self):
        self.client = ArcGISClient()

    def test_retries_once_after_a_timeout(self, mock_get, _sleep):
        mock_get.side_effect = [requests.ReadTimeout(), arcgis_response({"ok": True})]

        self.assertEqual(self.client._make_request("https://example.test", {}), {"ok": True})
        self.assertEqual(mock_get.call_count, 2)

    def test_raises_timeout_error_when_every_attempt_times_out(self, mock_get, _sleep):
        mock_get.side_effect = requests.ReadTimeout()

        with self.assertRaises(ArcGISTimeoutError) as caught:
            self.client._make_request("https://example.test", {})
        self.assertEqual(mock_get.call_count, ArcGISClient.MAX_ATTEMPTS)
        self.assertEqual(caught.exception.status_code, 504)

    def test_connect_timeout_counts_as_a_timeout(self, mock_get, _sleep):
        mock_get.side_effect = requests.ConnectTimeout()  # also a ConnectionError subclass

        with self.assertRaises(ArcGISTimeoutError):
            self.client._make_request("https://example.test", {})

    def test_raises_connection_error_when_unreachable(self, mock_get, _sleep):
        mock_get.side_effect = requests.ConnectionError()

        with self.assertRaises(ArcGISConnectionError) as caught:
            self.client._make_request("https://example.test", {})
        self.assertEqual(caught.exception.status_code, 503)

    def test_retries_gateway_errors(self, mock_get, _sleep):
        mock_get.side_effect = [arcgis_response({}, status_code=503), arcgis_response({"ok": True})]

        self.assertEqual(self.client._make_request("https://example.test", {}), {"ok": True})

    def test_does_not_retry_other_http_errors(self, mock_get, _sleep):
        mock_get.return_value = arcgis_response({}, status_code=404)

        with self.assertRaises(ArcGISServiceError):
            self.client._make_request("https://example.test", {})
        self.assertEqual(mock_get.call_count, 1)

    def test_passes_separate_connect_and_read_timeouts(self, mock_get, _sleep):
        mock_get.return_value = arcgis_response({})

        self.client._make_request("https://example.test", {})
        self.assertEqual(
            mock_get.call_args.kwargs["timeout"],
            (ArcGISClient.CONNECT_TIMEOUT_SECONDS, ArcGISClient.READ_TIMEOUT_SECONDS),
        )


@patch("gis_pipeline.time.sleep")
@patch("gis_pipeline.requests.Session.get")
class PartialResultTests(unittest.TestCase):
    def setUp(self):
        self.service = ReferenceMarkerService()
        self.point = {"x": -74.3, "y": 41.7}

    def test_returns_partial_results_when_some_layers_time_out(self, mock_get, _sleep):
        def by_layer(url, **kwargs):
            if url.endswith("/9/query"):
                raise requests.ReadTimeout()
            return arcgis_response(layer_body(feature(1, "44 8201 1001", 10, 20)))
        mock_get.side_effect = by_layer

        result = self.service.find_nearby(self.point, 4326)

        self.assertTrue(result.is_partial)
        self.assertEqual(len(result.markers), 1)

    def test_complete_results_are_not_partial(self, mock_get, _sleep):
        mock_get.return_value = arcgis_response(layer_body(feature(1, "44 8201 1001", 10, 20)))

        self.assertFalse(self.service.find_nearby(self.point, 4326).is_partial)

    def test_raises_timeout_when_every_layer_fails(self, mock_get, _sleep):
        def by_layer(url, **kwargs):
            if url.endswith("/1/query"):
                return arcgis_response({"error": {"code": 500, "message": "boom"}})
            raise requests.ReadTimeout()
        mock_get.side_effect = by_layer

        # Mixed failures: the timeout is reported, as the most likely cause
        with self.assertRaises(ArcGISTimeoutError):
            self.service.find_nearby(self.point, 4326)


@patch("gis_pipeline.time.sleep")
@patch("gis_pipeline.requests.Session.get")
class ApiErrorResponseTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        import main
        self.client = TestClient(main.app)

    def test_timeout_becomes_504_with_friendly_message(self, mock_get, _sleep):
        mock_get.side_effect = requests.ReadTimeout()

        response = self.client.get("/suggestions", params={"text": "Route 44"})

        self.assertEqual(response.status_code, 504)
        self.assertIn("taking too long", response.json()["detail"])
        self.assertIn("NYS address lookup service", response.json()["detail"])

    def test_unreachable_becomes_503(self, mock_get, _sleep):
        mock_get.side_effect = requests.ConnectionError()

        response = self.client.post("/geocode", json={"magic_key": "abc"})

        self.assertEqual(response.status_code, 503)
        self.assertIn("internet connection", response.json()["detail"])

    def test_partial_results_set_header(self, mock_get, _sleep):
        def by_layer(url, **kwargs):
            if url.endswith("/9/query"):
                raise requests.ReadTimeout()
            return arcgis_response(layer_body(feature(1, "44 8201 1001", 10, 20)))
        mock_get.side_effect = by_layer

        response = self.client.post("/identify", json={"point": {"x": 1, "y": 2}, "sr": 26918})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_partial"])

    def test_complete_results_are_not_partial(self, mock_get, _sleep):
        mock_get.return_value = arcgis_response(layer_body())

        response = self.client.post("/identify", json={"point": {"x": 1, "y": 2}, "sr": 26918})

        self.assertFalse(response.json()["is_partial"])


class SlowHandler(BaseHTTPRequestHandler):
    """Answers every request after a delay that the test controls."""
    delay_seconds = 0.0
    requests_seen = 0

    def do_GET(self):
        type(self).requests_seen += 1
        time.sleep(type(self).delay_seconds)
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the client gave up waiting, as intended

    def log_message(self, *args):
        pass


class RealNetworkTimeoutTests(unittest.TestCase):
    """Uses a real local HTTP server (no mocks) to prove timeouts and retries fire."""

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), SlowHandler)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}/query"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        SlowHandler.requests_seen = 0

    def test_slow_server_times_out_after_retrying(self):
        SlowHandler.delay_seconds = 2  # well past the 0.3 s read timeout
        started = time.monotonic()

        with self.assertRaises(ArcGISTimeoutError):
            FastRetryClient()._make_request(self.url, {})

        elapsed = time.monotonic() - started
        self.assertEqual(SlowHandler.requests_seen, FastRetryClient.MAX_ATTEMPTS)
        self.assertLess(elapsed, 1.5, "the client should give up quickly, not wait for the server")

    def test_fast_server_succeeds(self):
        SlowHandler.delay_seconds = 0

        self.assertEqual(FastRetryClient()._make_request(self.url, {}), {"ok": True})
        self.assertEqual(SlowHandler.requests_seen, 1)


if __name__ == "__main__":
    unittest.main()
