"""NYSDOT region/county codes.

Every reference marker carries a two-digit region/county code (REGION_COUNTY_CODE,
also the first two digits on the panel's second line): the region, then the county's
number within that region, mostly in alphabetical order. Long Island (Region 10)
and New York City (Region 11) use codes starting with 0.

Source: NYSDOT Traffic Data Report, Appendix D "NYSDOT Region and County Codes",
cross-checked with nysroads.com/art-regions.php.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RegionCounty:
    code: str     # e.g. "86"
    county: str   # e.g. "Ulster County"
    region: int   # e.g. 8


class RegionCountyCodes:
    # code -> (county, region)
    _CODES = {
        # Region 1, Capital District
        "11": ("Albany", 1), "12": ("Essex", 1), "13": ("Greene", 1), "14": ("Rensselaer", 1),
        "15": ("Saratoga", 1), "16": ("Schenectady", 1), "17": ("Warren", 1), "18": ("Washington", 1),
        # Region 2, Mohawk Valley
        "21": ("Fulton", 2), "22": ("Hamilton", 2), "23": ("Herkimer", 2), "24": ("Madison", 2),
        "25": ("Montgomery", 2), "26": ("Oneida", 2),
        # Region 3, Central New York
        "31": ("Cayuga", 3), "32": ("Cortland", 3), "33": ("Onondaga", 3), "34": ("Oswego", 3),
        "35": ("Seneca", 3), "36": ("Tompkins", 3),
        # Region 4, Genesee Valley (Wayne moved here from Region 3, so it follows Wyoming)
        "41": ("Genesee", 4), "42": ("Livingston", 4), "43": ("Monroe", 4), "44": ("Ontario", 4),
        "45": ("Orleans", 4), "46": ("Wyoming", 4), "47": ("Wayne", 4),
        # Region 5, Western New York
        "51": ("Cattaraugus", 5), "52": ("Chautauqua", 5), "53": ("Erie", 5), "54": ("Niagara", 5),
        # Region 6, Western Southern Tier (Yates is 66; 65 was Tioga's old code)
        "61": ("Allegany", 6), "62": ("Chemung", 6), "63": ("Schuyler", 6), "64": ("Steuben", 6),
        "66": ("Yates", 6),
        # Region 7, North Country
        "71": ("Clinton", 7), "72": ("Franklin", 7), "73": ("Jefferson", 7), "74": ("Lewis", 7),
        "75": ("St. Lawrence", 7),
        # Region 8, Hudson Valley
        "81": ("Columbia", 8), "82": ("Dutchess", 8), "83": ("Orange", 8), "84": ("Putnam", 8),
        "85": ("Rockland", 8), "86": ("Ulster", 8), "87": ("Westchester", 8),
        # Region 9, Eastern Southern Tier
        "91": ("Broome", 9), "92": ("Chenango", 9), "93": ("Delaware", 9), "94": ("Otsego", 9),
        "95": ("Schoharie", 9), "96": ("Sullivan", 9), "97": ("Tioga", 9),
        # Region 10, Long Island
        "03": ("Nassau", 10), "07": ("Suffolk", 10),
        # Region 11, New York City
        "01": ("Bronx", 11), "02": ("Kings", 11), "04": ("New York", 11), "05": ("Queens", 11),
        "06": ("Richmond", 11),
        # Former codes that may still appear in older records
        "37": ("Wayne", 4), "65": ("Tioga", 9),
    }

    @classmethod
    def lookup(cls, code: Optional[str]) -> Optional[RegionCounty]:
        """Returns the county and region for a code like "86" (spaces ignored), or None if unknown."""
        key = "".join(str(code or "").split())
        if len(key) == 1:
            key = "0" + key  # a code stored as a number loses its leading zero
        entry = cls._CODES.get(key)
        if entry is None:
            return None
        county, region = entry
        return RegionCounty(code=key, county=f"{county} County", region=region)
