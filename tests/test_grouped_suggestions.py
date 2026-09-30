import unittest
from unittest.mock import patch

import requests

from gis_pipeline import ArcGISTimeoutError, GeocoderService
from tests.test_reference_marker_service import arcgis_response

SAMPLES = {
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

        self.assertEqual([g.label for g in groups], ["Intersections", "Roads", "Counties"])  # no empty "Towns & Cities"
        self.assertEqual([s["magicKey"] for s in groups[1].suggestions], ["s1", "s2"])
        self.assertEqual(groups[0].category, "Intersection")

    def test_other_groups_still_shown_when_one_category_fails(self, mock_get, _sleep):
        def flaky(url, params=None, **kwargs):
            if params["category"] == "Street Name":
                raise requests.ReadTimeout()
            return by_category(url, params)
        mock_get.side_effect = flaky

        groups = self.geocoder.suggest_grouped("Route 44")

        self.assertEqual([g.label for g in groups], ["Intersections", "Counties"])

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
        self.assertEqual([g["label"] for g in body["groups"]], ["Intersections", "Roads", "Counties"])
        self.assertEqual(body["groups"][2]["suggestions"], SAMPLES["Subregion"])


if __name__ == "__main__":
    unittest.main()
