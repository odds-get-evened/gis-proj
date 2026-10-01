"""Distances between map points, without external libraries.

Points can arrive in any spatial reference the app uses: latitude/longitude,
Web Mercator (map clicks, geocoder results, marker geometries) or UTM zone 18N
(typed coordinates). Each is converted to latitude/longitude first.
"""
import math
from typing import Dict, List, Optional, Tuple

from utm_projection import UTM_ZONE_18N

LatLon = Tuple[float, float]


class Geodesy:
    """Converts points to latitude/longitude and measures short ground distances."""
    # WGS 84 ellipsoid
    SEMI_MAJOR_AXIS_M = 6378137.0
    ECCENTRICITY_SQUARED = 0.00669437999014
    METERS_PER_MILE = 1609.344

    LAT_LON_WKIDS = {4326, 4269}                       # WGS 84, NAD83 (within ~1 m of each other)
    WEB_MERCATOR_WKIDS = {3857, 102100, 102113, 900913}
    UTM_18N_WKIDS = {26918}

    @classmethod
    def to_lat_lon(cls, x: float, y: float, wkid: int) -> Optional[LatLon]:
        """Returns (latitude, longitude) in degrees, or None for an unsupported spatial reference."""
        if wkid in cls.LAT_LON_WKIDS:
            return y, x
        if wkid in cls.WEB_MERCATOR_WKIDS:
            radius = cls.SEMI_MAJOR_AXIS_M
            longitude = math.degrees(x / radius)
            latitude = math.degrees(2 * math.atan(math.exp(y / radius)) - math.pi / 2)
            return latitude, longitude
        if wkid in cls.UTM_18N_WKIDS:
            return UTM_ZONE_18N.to_lat_lon(x, y)
        return None

    @classmethod
    def point_to_lat_lon(cls, point: Dict, wkid: int) -> Optional[LatLon]:
        return cls.to_lat_lon(point["x"], point["y"], wkid)

    @classmethod
    def distance_miles(cls, a: LatLon, b: LatLon) -> float:
        """Ground distance between two nearby points, in statute miles.

        Uses the ellipsoid's north-south and east-west radii of curvature at the
        points' mean latitude. Over the few miles the app works with, this agrees
        with a full geodesic calculation to well under a foot.
        """
        (lat1, lon1), (lat2, lon2) = a, b
        mean_lat = math.radians((lat1 + lat2) / 2)
        e2, axis = cls.ECCENTRICITY_SQUARED, cls.SEMI_MAJOR_AXIS_M
        denominator = 1 - e2 * math.sin(mean_lat) ** 2
        meridional_radius = axis * (1 - e2) / denominator ** 1.5       # north-south
        prime_vertical_radius = axis / math.sqrt(denominator)          # east-west
        north = math.radians(lat2 - lat1) * meridional_radius
        east = math.radians(lon2 - lon1) * prime_vertical_radius * math.cos(mean_lat)
        return math.hypot(north, east) / cls.METERS_PER_MILE

    @classmethod
    def circle(cls, center: LatLon, radius_miles: float, segments: int = 72) -> List[List[float]]:
        """A closed ring of [longitude, latitude] points radius_miles from center on the ground.

        Uses the ellipsoid's radii of curvature at the center's latitude. For a half-mile
        circle every point is within about an inch of radius_miles from the center, both
        by distance_miles and by a full geodesic calculation.
        """
        lat0, lon0 = center
        lat_rad = math.radians(lat0)
        e2, axis = cls.ECCENTRICITY_SQUARED, cls.SEMI_MAJOR_AXIS_M
        denominator = 1 - e2 * math.sin(lat_rad) ** 2
        meridional_radius = axis * (1 - e2) / denominator ** 1.5
        prime_vertical_radius = axis / math.sqrt(denominator)
        radius_m = radius_miles * cls.METERS_PER_MILE

        ring = []
        for i in range(segments):
            bearing = 2 * math.pi * i / segments  # clockwise from north
            north, east = radius_m * math.cos(bearing), radius_m * math.sin(bearing)
            lat = lat0 + math.degrees(north / meridional_radius)
            lon = lon0 + math.degrees(east / (prime_vertical_radius * math.cos(lat_rad)))
            ring.append([lon, lat])
        ring.append(list(ring[0]))  # close the ring
        return ring


def wkid_of(spatial_reference: Optional[Dict]) -> Optional[int]:
    """The wkid of an ArcGIS spatialReference object, preferring latestWkid."""
    if not spatial_reference:
        return None
    return spatial_reference.get("latestWkid") or spatial_reference.get("wkid")
