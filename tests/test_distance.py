import unittest
from unittest.mock import patch

from geodesy import Geodesy, wkid_of
from gis_pipeline import ReferenceMarkerService
from tests.test_reference_marker_service import arcgis_response

# Search location (the Kerhonkson UTM example) and nearby points, with ground
# distances computed by PROJ's geodesic on the WGS 84 ellipsoid
CENTER_LAT_LON = (41.771371, -74.328847)
CENTER_WEB_MERCATOR = (-8274249.399, 5126793.215)
CENTER_UTM = (555781.961, 4624609.962)
POINTS = [  # (lat, lon, web mercator x, web mercator y, miles from center)
    (41.7745, -74.3302, -8274400.015, 5127260.261, 0.226979),
    (41.769, -74.3201, -8273275.688, 5126439.326, 0.480634),
    (41.78, -74.34, -8275490.946, 5128081.267, 0.828638),
]


class GeodesyTests(unittest.TestCase):
    def test_distance_matches_proj(self):
        for lat, lon, _, _, miles in POINTS:
            self.assertAlmostEqual(Geodesy.distance_miles(CENTER_LAT_LON, (lat, lon)), miles, delta=1e-5)  # ~0.05 ft

    def test_converts_each_supported_spatial_reference(self):
        for wkid, (x, y) in [(3857, CENTER_WEB_MERCATOR), (102100, CENTER_WEB_MERCATOR), (26918, CENTER_UTM),
                             (4326, (CENTER_LAT_LON[1], CENTER_LAT_LON[0]))]:
            lat, lon = Geodesy.to_lat_lon(x, y, wkid)
            self.assertAlmostEqual(lat, CENTER_LAT_LON[0], places=5, msg=wkid)
            self.assertAlmostEqual(lon, CENTER_LAT_LON[1], places=5, msg=wkid)

    def test_unsupported_spatial_reference_returns_none(self):
        self.assertIsNone(Geodesy.to_lat_lon(1, 2, 2263))  # NY State Plane: not used by the app

    def test_wkid_prefers_latest(self):
        self.assertEqual(wkid_of({"wkid": 102100, "latestWkid": 3857}), 3857)
        self.assertEqual(wkid_of({"wkid": 26918}), 26918)
        self.assertIsNone(wkid_of(None))


def layer_with(*features):
    return {
        "fieldAliases": {"OBJECTID": "OBJECTID"},
        "spatialReference": {"wkid": 102100, "latestWkid": 3857},
        "features": list(features),
    }


# Markers returned out of order: farthest, nearest, middle, and one without a location
UNSORTED = layer_with(
    {"attributes": {"OBJECTID": 3}, "geometry": {"x": POINTS[2][2], "y": POINTS[2][3]}},
    {"attributes": {"OBJECTID": 1}, "geometry": {"x": POINTS[0][2], "y": POINTS[0][3]}},
    {"attributes": {"OBJECTID": 9}, "geometry": None},
    {"attributes": {"OBJECTID": 2}, "geometry": {"x": POINTS[1][2], "y": POINTS[1][3]}},
)


@patch("gis_pipeline.requests.Session.get")
class FindNearbyDistanceTests(unittest.TestCase):
    def setUp(self):
        self.service = ReferenceMarkerService()

    def assertClosestFirst(self, result):
        self.assertEqual([m["attributes"]["OBJECTID"] for m in result.markers], [1, 2, 3, 9])
        for marker, (_, _, _, _, miles) in zip(result.markers, POINTS):
            self.assertAlmostEqual(marker["distance_miles"], miles, delta=1e-4)
        self.assertIsNone(result.markers[3]["distance_miles"])  # no location: listed last

    def test_sorted_closest_first_from_lat_lon(self, mock_get):
        mock_get.return_value = arcgis_response(UNSORTED)
        self.assertClosestFirst(self.service.find_nearby({"x": CENTER_LAT_LON[1], "y": CENTER_LAT_LON[0]}, 4326))

    def test_sorted_closest_first_from_utm(self, mock_get):
        mock_get.return_value = arcgis_response(UNSORTED)
        self.assertClosestFirst(self.service.find_nearby({"x": CENTER_UTM[0], "y": CENTER_UTM[1]}, 26918))

    def test_sorted_closest_first_from_map_click(self, mock_get):
        mock_get.return_value = arcgis_response(UNSORTED)
        self.assertClosestFirst(self.service.find_nearby({"x": CENTER_WEB_MERCATOR[0], "y": CENTER_WEB_MERCATOR[1]}, 102100))

    def test_identify_endpoint_includes_distance(self, mock_get):
        from fastapi.testclient import TestClient
        import main
        mock_get.return_value = arcgis_response(UNSORTED)

        body = TestClient(main.app).post("/identify", json={"point": {"x": CENTER_UTM[0], "y": CENTER_UTM[1]}, "sr": 26918}).json()

        self.assertEqual([m["attributes"]["OBJECTID"] for m in body["markers"]], [1, 2, 3, 9])
        self.assertAlmostEqual(body["markers"][0]["distance_miles"], POINTS[0][4], delta=1e-4)


if __name__ == "__main__":
    unittest.main()


class SearchAreaTests(unittest.TestCase):
    def test_circle_points_are_the_radius_from_the_center(self):
        ring = Geodesy.circle(CENTER_LAT_LON, 0.5)
        self.assertEqual(len(ring), 73)
        self.assertEqual(ring[0], ring[-1])  # closed
        for lon, lat in ring:
            # 2e-5 miles is about 1.3 inches
            self.assertAlmostEqual(Geodesy.distance_miles(CENTER_LAT_LON, (lat, lon)), 0.5, delta=2e-5)

    def test_circle_starts_due_north_and_runs_clockwise(self):
        ring = Geodesy.circle(CENTER_LAT_LON, 0.5)
        (lon_n, lat_n), (lon_e, lat_e) = ring[0], ring[18]  # 0 and 90 degrees
        self.assertAlmostEqual(lon_n, CENTER_LAT_LON[1], places=9)
        self.assertGreater(lat_n, CENTER_LAT_LON[0])
        self.assertAlmostEqual(lat_e, CENTER_LAT_LON[0], places=9)
        self.assertGreater(lon_e, CENTER_LAT_LON[1])


@patch("gis_pipeline.requests.Session.get")
class FindNearbySearchAreaTests(unittest.TestCase):
    def test_search_area_is_centered_on_the_search_point(self, mock_get):
        mock_get.return_value = arcgis_response(layer_with())

        area = ReferenceMarkerService().find_nearby({"x": CENTER_UTM[0], "y": CENTER_UTM[1]}, 26918, radius_miles=0.5).search_area

        self.assertEqual(area["spatialReference"], {"wkid": 4326})
        ring = area["rings"][0]
        lons, lats = [p[0] for p in ring], [p[1] for p in ring]
        self.assertAlmostEqual((min(lats) + max(lats)) / 2, CENTER_LAT_LON[0], places=5)
        self.assertAlmostEqual((min(lons) + max(lons)) / 2, CENTER_LAT_LON[1], places=5)
        for lon, lat in ring:
            self.assertAlmostEqual(Geodesy.distance_miles(CENTER_LAT_LON, (lat, lon)), 0.5, delta=1e-4)

    def test_unsupported_spatial_reference_has_no_search_area(self, mock_get):
        mock_get.return_value = arcgis_response(layer_with())

        self.assertIsNone(ReferenceMarkerService().find_nearby({"x": 1, "y": 2}, 2263).search_area)


@patch("gis_pipeline.requests.Session.get")
class RadiusTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        import main
        self.client = TestClient(main.app)

    def test_each_offered_radius_is_used_for_the_search_and_the_circle(self, mock_get):
        for miles in (0.25, 0.5, 1):
            mock_get.reset_mock()
            mock_get.return_value = arcgis_response(layer_with())

            body = self.client.post("/identify", json={"point": {"x": CENTER_UTM[0], "y": CENTER_UTM[1]},
                                                       "sr": 26918, "radius_miles": miles}).json()

            self.assertTrue(all(c.kwargs["params"]["distance"] == miles for c in mock_get.call_args_list))
            lon, lat = body["search_area"]["rings"][0][0]
            self.assertAlmostEqual(Geodesy.distance_miles(CENTER_LAT_LON, (lat, lon)), miles, delta=1e-4)

    def test_radius_defaults_to_half_a_mile(self, mock_get):
        mock_get.return_value = arcgis_response(layer_with())

        self.client.post("/identify", json={"point": {"x": 1, "y": 2}, "sr": 26918})

        self.assertEqual(mock_get.call_args.kwargs["params"]["distance"], 0.5)

    def test_unreasonable_radii_are_refused(self, mock_get):
        for miles in (0, -1, 1.5, 50):
            response = self.client.post("/identify", json={"point": {"x": 1, "y": 2}, "sr": 26918, "radius_miles": miles})
            self.assertEqual(response.status_code, 422, miles)
        mock_get.assert_not_called()
