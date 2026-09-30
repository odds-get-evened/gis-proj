import unittest
from unittest.mock import patch

from gis_pipeline import CoordinateError, CoordinateParser
from tests.test_reference_marker_service import arcgis_response


class LatLonTests(unittest.TestCase):
    def setUp(self):
        self.parser = CoordinateParser()

    def assertLatLon(self, text, lat, lon):
        result = self.parser.parse(text)
        self.assertIsNotNone(result, text)
        self.assertEqual(result.sr, 4326)
        self.assertEqual((result.point["y"], result.point["x"]), (lat, lon))
        return result

    def test_latitude_then_longitude(self):
        result = self.assertLatLon("41.7, -74.3", 41.7, -74.3)
        self.assertIn("latitude, longitude", result.description)

    def test_longitude_then_latitude_is_not_swapped_wrongly(self):
        result = self.assertLatLon("-74.3, 41.7", 41.7, -74.3)
        self.assertIn("longitude, latitude", result.description)

    def test_missing_minus_sign_is_read_as_west(self):
        result = self.assertLatLon("41.7 74.3", 41.7, -74.3)
        self.assertIn("west longitude", result.description)

    def test_accepts_spaces_semicolons_and_degree_signs(self):
        self.assertLatLon("41.7 -74.3", 41.7, -74.3)
        self.assertLatLon("42;-73.75", 42.0, -73.75)
        self.assertLatLon("  41.7°, -74.3°  ", 41.7, -74.3)
        self.assertLatLon("+41.7, -74.3", 41.7, -74.3)

    def test_outside_new_york_raises_a_helpful_error(self):
        with self.assertRaises(CoordinateError) as caught:
            self.parser.parse("10, 20")
        self.assertIn("outside New York", caught.exception.user_message)
        self.assertIn("41.7, -74.3", caught.exception.user_message)  # shows an example


class UtmTests(unittest.TestCase):
    def setUp(self):
        self.parser = CoordinateParser()

    def test_easting_then_northing(self):
        result = self.parser.parse("560638, 4621699")
        self.assertEqual((result.point, result.sr), ({"x": 560638.0, "y": 4621699.0}, 26918))

    def test_utm_includes_latitude_longitude_for_the_map_pin(self):
        display = self.parser.parse("555782, 4624610").display_point
        self.assertAlmostEqual(display["y"], 41.771371, places=5)
        self.assertAlmostEqual(display["x"], -74.328847, places=5)

    def test_northing_then_easting_is_not_swapped_wrongly(self):
        result = self.parser.parse("4621699, 560638")
        self.assertEqual(result.point, {"x": 560638.0, "y": 4621699.0})
        self.assertIn("northing, easting", result.description)

    def test_description_never_uses_scientific_notation(self):
        self.assertNotIn("e+", self.parser.parse("560638, 4621699").description)

    def test_outside_new_york_raises(self):
        with self.assertRaises(CoordinateError):
            self.parser.parse("9000000, 9000000")


class NotCoordinatesTests(unittest.TestCase):
    def test_text_and_mixed_numbers_fall_through_to_address_search(self):
        parser = CoordinateParser()
        for text in ["Route 44", "5700 Route 44 55, Kerhonkson, NY", "5700 44", "12345", "", "41.7, -74.3, 5"]:
            self.assertIsNone(parser.parse(text), text)


class SearchEndpointTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        import main
        self.client = TestClient(main.app)

    @patch("gis_pipeline.requests.Session.get")
    def test_coordinates_skip_the_address_lookup(self, mock_get):
        response = self.client.get("/search", params={"text": "-74.3, 41.7"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["type"], "coordinates")
        self.assertEqual((body["point"], body["sr"]), ({"x": -74.3, "y": 41.7}, 4326))
        self.assertEqual(body["display_point"], {"x": -74.3, "y": 41.7})
        mock_get.assert_not_called()

    @patch("gis_pipeline.requests.Session.get")
    def test_text_returns_address_suggestions(self, mock_get):
        mock_get.return_value = arcgis_response({"suggestions": [{"text": "Route 44", "magicKey": "k"}]})

        body = self.client.get("/search", params={"text": "Route 44"}).json()

        self.assertEqual(body["type"], "suggestions")
        self.assertIn({"text": "Route 44", "magicKey": "k"}, body["groups"][0]["suggestions"])

    def test_coordinates_outside_new_york_return_422_with_message(self):
        response = self.client.get("/search", params={"text": "10, 20"})

        self.assertEqual(response.status_code, 422)
        self.assertIn("outside New York", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
