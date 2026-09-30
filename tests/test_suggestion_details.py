import unittest
from unittest.mock import patch

import requests

from gis_pipeline import GeocoderService
from tests.test_reference_marker_service import arcgis_response

ROUTE_44 = {"text": "Route 44, Kerhonkson, NY", "magic_key": "k1"}
ULSTER = {"text": "Ulster County, NY", "magic_key": "k2"}

# Shape taken from a real NYS geocoder response
KERHONKSON_CANDIDATE = {
    "spatialReference": {"wkid": 102100, "latestWkid": 3857},
    "candidates": [{
        "address": "United States Route 44, Kerhonkson, NY, 12446",
        "location": {"x": -8274000.5, "y": 5124000.25},
        "score": 100,
        "attributes": {"City": "Kerhonkson", "Subregion": "Ulster"},
    }],
}


@patch("gis_pipeline.time.sleep")
@patch("gis_pipeline.requests.Session.get")
class SuggestionDetailsTests(unittest.TestCase):
    def setUp(self):
        self.geocoder = GeocoderService()

    def test_sends_text_and_magic_key_and_asks_for_town_and_county(self, mock_get, _sleep):
        mock_get.return_value = arcgis_response(KERHONKSON_CANDIDATE)

        self.geocoder.suggestion_details([ROUTE_44])

        params = mock_get.call_args.kwargs["params"]
        self.assertEqual(mock_get.call_args.args[0], GeocoderService.FIND_URL)
        self.assertEqual((params["SingleLine"], params["magicKey"]), ("Route 44, Kerhonkson, NY", "k1"))
        self.assertEqual(params["outFields"], "City,Subregion")
        self.assertEqual(params["maxLocations"], 1)

    def test_returns_town_county_and_location(self, mock_get, _sleep):
        mock_get.return_value = arcgis_response(KERHONKSON_CANDIDATE)

        details = self.geocoder.suggestion_details([ROUTE_44])[0]

        self.assertTrue(details.found)
        self.assertEqual((details.city, details.county), ("Kerhonkson", "Ulster County"))
        self.assertEqual(details.location, {"x": -8274000.5, "y": 5124000.25})
        self.assertEqual(details.spatial_reference["latestWkid"], 3857)
        self.assertEqual(details.magic_key, "k1")

    def test_one_failed_lookup_does_not_affect_the_others(self, mock_get, _sleep):
        def by_key(url, params=None, **kwargs):
            if params["magicKey"] == "k2":
                raise requests.ReadTimeout()
            return arcgis_response(KERHONKSON_CANDIDATE)
        mock_get.side_effect = by_key

        first, second = self.geocoder.suggestion_details([ROUTE_44, ULSTER])

        self.assertTrue(first.found)
        self.assertFalse(second.found)
        self.assertEqual(second.magic_key, "k2")

    def test_no_candidates_means_not_found(self, mock_get, _sleep):
        mock_get.return_value = arcgis_response({"candidates": []})

        self.assertFalse(self.geocoder.suggestion_details([ROUTE_44])[0].found)

    def test_empty_request_makes_no_calls(self, mock_get, _sleep):
        self.assertEqual(self.geocoder.suggestion_details([]), [])
        mock_get.assert_not_called()


class CountyNameTests(unittest.TestCase):
    def test_formats_county_names(self):
        name = GeocoderService._county_name
        self.assertEqual(name("Ulster"), "Ulster County")
        self.assertEqual(name("  Saint Lawrence "), "Saint Lawrence County")
        self.assertEqual(name("Albany County"), "Albany County")  # not doubled
        self.assertEqual(name(""), "")
        self.assertEqual(name(None), "")


class SuggestionDetailsEndpointTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        import main
        self.client = TestClient(main.app)

    @patch("gis_pipeline.requests.Session.get")
    def test_returns_details_in_request_order(self, mock_get):
        mock_get.return_value = arcgis_response(KERHONKSON_CANDIDATE)

        response = self.client.post("/suggestion-details", json={"suggestions": [ROUTE_44, ULSTER]})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual([d["magic_key"] for d in body], ["k1", "k2"])
        self.assertEqual(body[0]["county"], "Ulster County")

    def test_rejects_more_than_25_suggestions(self):
        many = [{"text": f"Place {i}", "magic_key": str(i)} for i in range(26)]

        response = self.client.post("/suggestion-details", json={"suggestions": many})

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
