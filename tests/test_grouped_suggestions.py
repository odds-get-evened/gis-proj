import unittest
from unittest.mock import patch

import requests

from gis_pipeline import ArcGISTimeoutError, GeocoderService
from tests.test_reference_marker_service import arcgis_response

SAMPLES = {
    "Address": [{"text": "5700 Route 44 55, Kerhonkson, NY", "magicKey": "a1"}],
    "Intersection": [{"text": "Route 44 & Main St, Kerhonkson, NY", "magicKey": "i1"}],
    "Street Name": [{"text": "Route 44, Kerhonkson, NY", "magicKey": "s1"}, {"text": "Route 44, Pleasant Valley, NY", "magicKey": "s2"}],
    "City": [],
    "Subregion": [{"text": "Ulster County, NY", "magicKey": "c1"}],
}


def by_category(url, params=None, **kwargs):
    return arcgis_response({"suggestions": SAMPLES[params["category"]]})


@patch("gis_pipeline.time.sleep")
@patch("gis_pipeline.requests.Session.get")
class SuggestGroupedTests(unittest.TestCase):
    def setUp(self):
        self.geocoder = GeocoderService()

    def test_requests_each_category_separately(self, mock_get, _sleep):
        mock_get.side_effect = by_category

        self.geocoder.suggest_grouped("Route 44")

        requested = sorted(call.kwargs["params"]["category"] for call in mock_get.call_args_list)
        self.assertEqual(requested, sorted(SAMPLES))
        for call in mock_get.call_args_list:
            self.assertEqual(call.kwargs["params"]["text"], "Route 44")
            self.assertEqual(call.kwargs["params"]["maxSuggestions"], GeocoderService.SUGGESTIONS_PER_CATEGORY)

    def test_groups_are_labeled_ordered_and_empty_ones_dropped(self, mock_get, _sleep):
        mock_get.side_effect = by_category

        groups = self.geocoder.suggest_grouped("Route 44")

        self.assertEqual([g.label for g in groups], ["Addresses", "Intersections", "Roads", "Counties"])  # no empty "Towns & Cities"
        self.assertEqual([s["magicKey"] for s in groups[2].suggestions], ["s1", "s2"])  # relevance order kept
        self.assertEqual(groups[0].category, "Address")

    def test_same_place_is_shown_once_in_the_most_specific_group(self, mock_get, _sleep):
        duplicates = {
            "Address": [],
            "Intersection": [],
            "Street Name": [{"text": "Kerhonkson, NY", "magicKey": "street"}, {"text": "Route 44, Kerhonkson, NY", "magicKey": "s1"}],
            "City": [{"text": "kerhonkson,  NY", "magicKey": "city"}, {"text": "Accord, NY", "magicKey": "accord"}],
            "Subregion": [],
        }
        mock_get.side_effect = lambda url, params=None, **kw: arcgis_response({"suggestions": duplicates[params["category"]]})

        groups = self.geocoder.suggest_grouped("Kerhonkson")

        self.assertEqual([s["magicKey"] for s in groups[0].suggestions], ["street", "s1"])
        self.assertEqual([s["magicKey"] for s in groups[1].suggestions], ["accord"])  # case/space variant dropped

    def test_unsupported_category_is_simply_left_out(self, mock_get, _sleep):
        def no_address_category(url, params=None, **kwargs):
            if params["category"] == "Address":
                return arcgis_response({"error": {"code": 400, "message": "Invalid category"}})
            return by_category(url, params)
        mock_get.side_effect = no_address_category

        groups = self.geocoder.suggest_grouped("Route 44")

        self.assertEqual([g.label for g in groups], ["Intersections", "Roads", "Counties"])

    def test_other_groups_still_shown_when_one_category_fails(self, mock_get, _sleep):
        def flaky(url, params=None, **kwargs):
            if params["category"] == "Street Name":
                raise requests.ReadTimeout()
            return by_category(url, params)
        mock_get.side_effect = flaky

        groups = self.geocoder.suggest_grouped("Route 44")

        self.assertEqual([g.label for g in groups], ["Addresses", "Intersections", "Counties"])

    def test_raises_when_every_category_fails(self, mock_get, _sleep):
        mock_get.side_effect = requests.ReadTimeout()

        with self.assertRaises(ArcGISTimeoutError):
            self.geocoder.suggest_grouped("Route 44")


class SearchEndpointGroupsTests(unittest.TestCase):
    @patch("gis_pipeline.requests.Session.get")
    def test_search_returns_groups(self, mock_get):
        from fastapi.testclient import TestClient
        import main
        mock_get.side_effect = by_category

        body = TestClient(main.app).get("/search", params={"text": "Route 44"}).json()

        self.assertEqual(body["type"], "suggestions")
        self.assertEqual([g["label"] for g in body["groups"]], ["Addresses", "Intersections", "Roads", "Counties"])
        self.assertEqual(body["groups"][3]["suggestions"], SAMPLES["Subregion"])


if __name__ == "__main__":
    unittest.main()
