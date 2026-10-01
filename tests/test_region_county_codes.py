import unittest
from unittest.mock import patch

from gis_pipeline import ReferenceMarkerService
from nysdot_codes import RegionCountyCodes
from tests.test_reference_marker_service import arcgis_response


class RegionCountyCodeTests(unittest.TestCase):
    def assertCode(self, code, county, region):
        place = RegionCountyCodes.lookup(code)
        self.assertIsNotNone(place, code)
        self.assertEqual((place.county, place.region), (county, region), code)

    def test_regular_codes(self):
        self.assertCode("86", "Ulster County", 8)     # confirmed by real marker data
        self.assertCode("11", "Albany County", 1)
        self.assertCode("53", "Erie County", 5)
        self.assertCode("75", "St. Lawrence County", 7)

    def test_codes_out_of_alphabetical_order(self):
        self.assertCode("66", "Yates County", 6)
        self.assertCode("46", "Wyoming County", 4)
        self.assertCode("47", "Wayne County", 4)
        self.assertCode("97", "Tioga County", 9)

    def test_long_island_and_new_york_city(self):
        self.assertCode("03", "Nassau County", 10)
        self.assertCode("07", "Suffolk County", 10)
        self.assertCode("01", "Bronx County", 11)
        self.assertCode("04", "New York County", 11)
        self.assertCode("06", "Richmond County", 11)

    def test_former_codes(self):
        self.assertCode("37", "Wayne County", 4)
        self.assertCode("65", "Tioga County", 9)

    def test_tolerates_spaces_and_lost_leading_zero(self):
        self.assertCode(" 86 ", "Ulster County", 8)
        self.assertCode("3", "Nassau County", 10)

    def test_unknown_codes(self):
        for code in ["99", "", None, "8"]:
            self.assertIsNone(RegionCountyCodes.lookup(code), code)

    def test_all_62_counties_are_covered(self):
        counties = {county for county, _ in RegionCountyCodes._CODES.values()}
        self.assertEqual(len(counties), 62)


def layer(*features):
    return {"fieldAliases": {"OBJECTID": "OBJECTID", "REFERENCE_MARKER_PANEL": "Reference Marker Number",
                             "REGION_COUNTY_CODE": "Regional County Code"},
            "spatialReference": {"wkid": 102100, "latestWkid": 3857},
            "features": list(features)}


@patch("gis_pipeline.requests.Session.get")
class MarkerSummaryTests(unittest.TestCase):
    def setUp(self):
        self.service = ReferenceMarkerService()
        self.point = {"x": -74.3, "y": 41.7}

    def test_each_marker_has_a_readable_summary(self, mock_get):
        mock_get.return_value = arcgis_response(layer(
            {"attributes": {"OBJECTID": 1, "REFERENCE_MARKER_PANEL": " 44 86011035", "REGION_COUNTY_CODE": "86"},
             "geometry": {"x": 1, "y": 2}}))

        marker = self.service.find_nearby(self.point, 4326).markers[0]

        self.assertEqual(marker["summary"], {"number": "44 8601 1035", "route": "44", "county": "Ulster County",
                                             "region": 8, "region_county_code": "86"})
        self.assertEqual(marker["attributes"]["Reference Marker Number"], " 44 86011035")  # raw data kept for Details

    def test_county_falls_back_to_the_panel_digits(self, mock_get):
        mock_get.return_value = arcgis_response(layer(
            {"attributes": {"OBJECTID": 1, "REFERENCE_MARKER_PANEL": " 9W 82011001"}, "geometry": {"x": 1, "y": 2}}))

        summary = self.service.find_nearby(self.point, 4326).markers[0]["summary"]

        self.assertEqual((summary["route"], summary["county"]), ("9W", "Dutchess County"))

    def test_unknown_code_leaves_county_empty_but_keeps_the_number(self, mock_get):
        mock_get.return_value = arcgis_response(layer(
            {"attributes": {"OBJECTID": 1, "REFERENCE_MARKER_PANEL": " 44 99011035", "REGION_COUNTY_CODE": "99"},
             "geometry": {"x": 1, "y": 2}}))

        summary = self.service.find_nearby(self.point, 4326).markers[0]["summary"]

        self.assertEqual(summary["number"], "44 9901 1035")
        self.assertIsNone(summary["county"])
        self.assertEqual(summary["region_county_code"], "99")

    def test_number_search_results_have_summaries_too(self, mock_get):
        from gis_pipeline import MarkerNumber
        mock_get.return_value = arcgis_response(layer(
            {"attributes": {"OBJECTID": 1, "REFERENCE_MARKER_PANEL": " 44 86011035", "REGION_COUNTY_CODE": "86"},
             "geometry": {"x": 1, "y": 2}}))

        marker = self.service.find_by_number(MarkerNumber("44", "8601")).markers[0]

        self.assertEqual(marker["summary"]["county"], "Ulster County")


if __name__ == "__main__":
    unittest.main()
