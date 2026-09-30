"""Converts UTM coordinates to latitude/longitude without external libraries.

Used to place typed UTM coordinates on the map, which draws latitude/longitude
natively. The marker search itself still sends the original UTM values to the
NYSDOT service, so this only affects where the search pin is drawn.
"""
import math
from typing import Tuple


class TransverseMercatorZone:
    """Inverse transverse Mercator projection for one UTM zone on the GRS 80 ellipsoid (NAD83).

    Uses the series from Snyder, "Map Projections: A Working Manual" (USGS Professional
    Paper 1395), equations 8-18 to 8-25. Across New York this agrees with PROJ to within
    a few centimeters, far finer than a map pin. NAD83 and WGS 84 differ by about a
    meter, which is also negligible at map scale.
    """
    SEMI_MAJOR_AXIS = 6378137.0
    FLATTENING = 1 / 298.257222101
    SCALE_FACTOR = 0.9996
    FALSE_EASTING = 500_000.0

    def __init__(self, zone: int):
        self.central_meridian = math.radians(zone * 6 - 183)
        f = self.FLATTENING
        self._e2 = 2 * f - f * f                       # first eccentricity squared
        self._ep2 = self._e2 / (1 - self._e2)          # second eccentricity squared
        root = math.sqrt(1 - self._e2)
        self._e1 = (1 - root) / (1 + root)

    def to_lat_lon(self, easting: float, northing: float) -> Tuple[float, float]:
        """Returns (latitude, longitude) in decimal degrees for a northern-hemisphere point."""
        a, e2, ep2, e1, k0 = self.SEMI_MAJOR_AXIS, self._e2, self._ep2, self._e1, self.SCALE_FACTOR

        meridional_arc = northing / k0
        mu = meridional_arc / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
        phi1 = (
            mu
            + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
            + (1097 * e1 ** 4 / 512) * math.sin(8 * mu)
        )

        sin1, cos1, tan1 = math.sin(phi1), math.cos(phi1), math.tan(phi1)
        c1 = ep2 * cos1 ** 2
        t1 = tan1 ** 2
        n1 = a / math.sqrt(1 - e2 * sin1 ** 2)
        r1 = a * (1 - e2) / (1 - e2 * sin1 ** 2) ** 1.5
        d = (easting - self.FALSE_EASTING) / (n1 * k0)

        latitude = phi1 - (n1 * tan1 / r1) * (
            d ** 2 / 2
            - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * ep2) * d ** 4 / 24
            + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * ep2 - 3 * c1 ** 2) * d ** 6 / 720
        )
        longitude = self.central_meridian + (
            d
            - (1 + 2 * t1 + c1) * d ** 3 / 6
            + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * ep2 + 24 * t1 ** 2) * d ** 5 / 120
        ) / cos1

        return math.degrees(latitude), math.degrees(longitude)


# The NYSDOT reference marker service uses UTM zone 18N (EPSG:26918) statewide
UTM_ZONE_18N = TransverseMercatorZone(18)
