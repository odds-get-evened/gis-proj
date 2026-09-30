import unittest

from utm_projection import UTM_ZONE_18N


class UtmToLatLonTests(unittest.TestCase):
    # Reference latitude/longitude (NAD83) computed with PROJ (pyproj) for EPSG:26918
    REFERENCE_POINTS = [
        (555782, 4624610, 41.77137134, -74.32884653),  # Kerhonkson (reported in the app)
        (560638, 4621699, 41.74479780, -74.27072176),  # README example
        (105724, 4700000, 42.35228197, -79.78675003),  # far west edge of NY
        (763909, 4985388, 44.97287447, -71.65313384),  # far northeast corner of NY
        (500000, 4500000, 40.65085652, -75.00000000),  # central meridian
    ]

    def test_matches_proj_across_new_york(self):
        for easting, northing, lat, lon in self.REFERENCE_POINTS:
            got_lat, got_lon = UTM_ZONE_18N.to_lat_lon(easting, northing)
            # 1e-6 degrees is about 10 cm on the ground
            self.assertAlmostEqual(got_lat, lat, delta=1e-6, msg=f"{easting}, {northing}")
            self.assertAlmostEqual(got_lon, lon, delta=1e-6, msg=f"{easting}, {northing}")


if __name__ == "__main__":
    unittest.main()
