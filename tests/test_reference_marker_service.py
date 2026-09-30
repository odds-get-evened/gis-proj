import unittest
from unittest.mock import MagicMock, patch

from gis_pipeline import ArcGISError, ReferenceMarkerService


def arcgis_response(body):
    """Builds a fake requests.Response returning the given JSON body."""
    response = MagicMock()
    response.json.return_value = body
    response.raise_for_status.return_value = None
    return response


def layer_body(*features):
    return {
        "fieldAliases": {"OBJECTID": "OBJECTID", "REFERENCE_MARKER_PANEL": "Reference Marker Number"},
        "spatialReference": {"wkid": 102100, "latestWkid": 3857},
        "features": list(features),
    }


def feature(object_id, panel, x, y):
    return {"attributes": {"OBJECTID": object_id, "REFERENCE_MARKER_PANEL": panel}, "geometry": {"x": x, "y": y}}


class FindNearbyTests(unittest.TestCase):
    def setUp(self):
        self.service = ReferenceMarkerService()
        self.point = {"x": -74.3, "y": 41.7}

    @patch("gis_pipeline.requests.get")
    def test_queries_every_layer_with_a_true_mile_distance(self, mock_get):
        mock_get.return_value = arcgis_response(layer_body())

        self.service.find_nearby(self.point, 4326, radius_miles=0.5)

        urls = sorted(call.args[0] for call in mock_get.call_args_list)
        expected = sorted(f"{ReferenceMarkerService.MAPSERVER_URL}/{i}/query" for i in ReferenceMarkerService.LAYER_IDS)
        self.assertEqual(urls, expected)
        for call in mock_get.call_args_list:
            params = call.kwargs["params"]
            self.assertEqual(params["distance"], 0.5)
            self.assertEqual(params["units"], "esriSRUnit_StatuteMile")
            self.assertEqual(params["inSR"], 4326)
            self.assertEqual(params["geometry"], "-74.3,41.7")
            self.assertNotIn("tolerance", params)  # the old pixel-based search is gone
            self.assertIn("timeout", call.kwargs)

    @patch("gis_pipeline.requests.get")
    def test_removes_duplicates_across_layers(self, mock_get):
        mock_get.return_value = arcgis_response(layer_body(feature(1, "44 8201 1001", 10, 20), feature(2, "44 8201 1002", 30, 40)))

        markers = self.service.find_nearby(self.point, 4326)

        self.assertEqual(sorted(m["attributes"]["OBJECTID"] for m in markers), [1, 2])

    @patch("gis_pipeline.requests.get")
    def test_uses_display_names_and_attaches_spatial_reference(self, mock_get):
        mock_get.return_value = arcgis_response(layer_body(feature(7, "44 8201 1007", 10, 20)))

        marker = self.service.find_nearby(self.point, 4326)[0]

        self.assertEqual(marker["attributes"]["Reference Marker Number"], "44 8201 1007")
        self.assertNotIn("REFERENCE_MARKER_PANEL", marker["attributes"])
        self.assertEqual(marker["geometry"]["spatialReference"]["latestWkid"], 3857)
        self.assertEqual((marker["geometry"]["x"], marker["geometry"]["y"]), (10, 20))

    @patch("gis_pipeline.requests.get")
    def test_raises_when_service_reports_an_error(self, mock_get):
        mock_get.return_value = arcgis_response({"error": {"code": 400, "message": "Invalid geometry"}})

        with self.assertRaises(ArcGISError):
            self.service.find_nearby(self.point, 4326)


class IdentifyEndpointTests(unittest.TestCase):
    @patch("gis_pipeline.requests.get")
    def test_identify_returns_marker_list(self, mock_get):
        from fastapi.testclient import TestClient
        import main

        mock_get.return_value = arcgis_response(layer_body(feature(3, "44 8201 1003", 1, 2)))
        client = TestClient(main.app)

        response = client.post("/identify", json={"point": {"x": 560638, "y": 4621699}, "sr": 26918})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["attributes"]["OBJECTID"], 3)
        self.assertIn("geometry", body[0])


if __name__ == "__main__":
    unittest.main()
