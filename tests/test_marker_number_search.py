import unittest
from unittest.mock import patch

from gis_pipeline import MarkerNumber, MarkerNumberParser, ReferenceMarkerService
from tests.test_reference_marker_service import arcgis_response


def stored_marker(object_id, panel, x=10.0, y=20.0):
    """A feature as the NYSDOT service returns it (stored panel format from a real response)."""
    return {"attributes": {"OBJECTID": object_id, "REFERENCE_MARKER_PANEL": panel, "REGION_COUNTY_CODE": panel.split()[-1][:2]},
            "geometry": {"x": x, "y": y}}


def marker_layer(*features):
    return {
        "fieldAliases": {"OBJECTID": "OBJECTID", "REFERENCE_MARKER_PANEL": "Reference Marker Number",
                         "REGION_COUNTY_CODE": "Regional County Code"},
        "spatialReference": {"wkid": 102100, "latestWkid": 3857},
        "features": list(features),
    }


class MarkerNumberParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = MarkerNumberParser()

    def test_accepts_spaced_unspaced_and_grouped_numbers(self):
        for text in ["44 8601 1035", "44 86011035", "4486011035", "  44  8601  1035 "]:
            self.assertEqual(self.parser.parse(text), MarkerNumber("44", "86011035"), text)

    def test_routes_with_letters_are_upper_cased(self):
        self.assertEqual(self.parser.parse("9w 8601 1035"), MarkerNumber("9W", "86011035"))
        self.assertEqual(self.parser.parse("990V 86011035"), MarkerNumber("990V", "86011035"))

    def test_partial_numbers_need_at_least_four_digits(self):
        self.assertEqual(self.parser.parse("44 8601"), MarkerNumber("44", "8601"))
        self.assertFalse(self.parser.parse("44 8601").is_complete)
        self.assertIsNone(self.parser.parse("44 860"))

    def test_addresses_and_coordinates_are_not_marker_numbers(self):
        for text in ["Route 44", "5700 Route 44 55, Kerhonkson", "41.7, -74.3", "560638, 4621699", "44", ""]:
            self.assertIsNone(self.parser.parse(text), text)


class MarkerNumberTests(unittest.TestCase):
    def test_reads_stored_values_whatever_the_padding(self):
        self.assertEqual(MarkerNumber.from_stored(" 44 86011035"), MarkerNumber("44", "86011035"))
        self.assertEqual(MarkerNumber.from_stored("990V86011035"), MarkerNumber("990V", "86011035"))
        self.assertIsNone(MarkerNumber.from_stored(None))
        self.assertIsNone(MarkerNumber.from_stored("86011035"))  # no route

    def test_display_groups_digits_like_the_panel(self):
        self.assertEqual(MarkerNumber("44", "86011035").display, "44 8601 1035")
        self.assertEqual(MarkerNumber("44", "860110").display, "44 8601 10")
        self.assertEqual(MarkerNumber("44", "8601").display, "44 8601")


@patch("gis_pipeline.requests.Session.get")
class FindByNumberTests(unittest.TestCase):
    def setUp(self):
        self.service = ReferenceMarkerService()

    def test_asks_the_server_for_a_loose_match(self, mock_get):
        mock_get.return_value = arcgis_response(marker_layer())

        self.service.find_by_number(MarkerNumber("44", "8601"))

        where = mock_get.call_args.kwargs["params"]["where"]
        self.assertEqual(where, "UPPER(REFERENCE_MARKER_PANEL) LIKE '%44%8601%'")

    def test_keeps_only_exact_route_and_digit_matches_in_marker_order(self, mock_get):
        mock_get.return_value = arcgis_response(marker_layer(
            stored_marker(3, " 44 86011040"),
            stored_marker(1, " 44 86011035"),
            stored_marker(2, "144 86011036"),   # different route that the loose match also finds
            stored_marker(4, " 44 86021035"),   # different control section
            stored_marker(5, " 44 86011039"),
        ))

        result = self.service.find_by_number(MarkerNumber("44", "860110"))

        self.assertEqual([m["number"] for m in result.markers], ["44 8601 1035", "44 8601 1039", "44 8601 1040"])
        self.assertEqual(result.total, 3)

    def test_limits_results_but_reports_the_total(self, mock_get):
        features = [stored_marker(i, f" 44 8601{1000 + i}") for i in range(25)]
        mock_get.return_value = arcgis_response(marker_layer(*features))

        result = self.service.find_by_number(MarkerNumber("44", "8601"))

        self.assertEqual(len(result.markers), ReferenceMarkerService.MAX_NUMBER_MATCHES)
        self.assertEqual(result.total, 25)

    def test_markers_without_a_location_are_skipped(self, mock_get):
        no_geometry = {"attributes": {"OBJECTID": 9, "REFERENCE_MARKER_PANEL": " 44 86011035"}, "geometry": None}
        mock_get.return_value = arcgis_response(marker_layer(no_geometry))

        self.assertEqual(self.service.find_by_number(MarkerNumber("44", "86011035")).markers, [])


class SearchEndpointMarkerTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        import main
        self.client = TestClient(main.app)

    @patch("gis_pipeline.requests.Session.get")
    def test_marker_number_returns_matching_markers(self, mock_get):
        mock_get.return_value = arcgis_response(marker_layer(stored_marker(1, " 44 86011035")))

        body = self.client.get("/search", params={"text": "44 8601 1035"}).json()

        self.assertEqual(body["type"], "markers")
        self.assertEqual((body["query"], body["is_complete"], body["total"]), ("44 8601 1035", True, 1))
        marker = body["markers"][0]
        self.assertEqual(marker["number"], "44 8601 1035")
        self.assertEqual(marker["attributes"]["OBJECTID"], 1)
        self.assertEqual(marker["geometry"]["spatialReference"]["latestWkid"], 3857)

    @patch("gis_pipeline.requests.Session.get")
    def test_no_marker_match_falls_back_to_place_suggestions(self, mock_get):
        def by_url(url, params=None, **kwargs):
            if "Ref_Marker" in url:
                return arcgis_response(marker_layer())
            return arcgis_response({"suggestions": [{"text": "209 5700 Rd, Somewhere, NY", "magicKey": "k"}]})
        mock_get.side_effect = by_url

        body = self.client.get("/search", params={"text": "209 5700"}).json()

        self.assertEqual(body["type"], "suggestions")

    @patch("gis_pipeline.requests.Session.get")
    def test_coordinates_still_win(self, mock_get):
        body = self.client.get("/search", params={"text": "41.7, -74.3"}).json()

        self.assertEqual(body["type"], "coordinates")
        mock_get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
