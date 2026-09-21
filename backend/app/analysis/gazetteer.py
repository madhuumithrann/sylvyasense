"""Bundled forest gazetteer.

Location search runs against this curated list rather than an external
geocoding service. That keeps search working offline and in restricted
networks, and it keeps the result set relevant: these are forest regions, not
every street in the world.

Coordinates are region centroids with an approximate extent, used to frame the
map. `demo` entries are additionally offered as one-click areas of interest.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any

from app.science.geo import Bounds


@dataclass(frozen=True)
class Place:
    name: str
    country: str
    biome: str
    lon: float
    lat: float
    span_deg: float
    demo: bool = False
    note: str = ""
    #: Regional and colloquial terms a user is likely to type ("amazon",
    #: "borneo"). These are searched but not displayed.
    aliases: tuple[str, ...] = ()

    def bounds(self) -> Bounds:
        half = self.span_deg / 2.0
        return Bounds(
            self.lon - half, self.lat - half, self.lon + half, self.lat + half
        )

    def aoi_geometry(self, size_deg: float | None = None) -> dict[str, Any]:
        """A square AOI centred on the place, sized for a single analysis run."""
        half = (size_deg if size_deg is not None else min(self.span_deg, 0.18)) / 2.0
        w, e = self.lon - half, self.lon + half
        s, n = self.lat - half, self.lat + half
        return {
            "type": "Polygon",
            "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "country": self.country,
            "biome": self.biome,
            "lon": self.lon,
            "lat": self.lat,
            "span_deg": self.span_deg,
            "bounds": self.bounds().as_list(),
            "demo": self.demo,
            "note": self.note,
        }


PLACES: tuple[Place, ...] = (
    # --- Demo areas (offered as one-click AOIs) --------------------------
    Place("Jaú National Park", "Brazil", "Tropical moist broadleaf", -61.75, -1.95, 0.9,
          demo=True, note="Rio Negro basin — one of the largest protected tropical forests on Earth",
          aliases=("amazon", "amazonia", "rio negro", "brasil", "jau")),
    Place("Tapajós National Forest", "Brazil", "Tropical moist broadleaf", -55.00, -3.30, 0.7,
          demo=True, note="Managed forest on the Amazon deforestation arc",
          aliases=("amazon", "amazonia", "tapajos", "arc of deforestation", "brasil")),
    Place("Salonga National Park", "DR Congo", "Tropical moist broadleaf", 21.00, -2.20, 1.0,
          demo=True, note="Central Congo basin, largest tropical rainforest reserve in Africa",
          aliases=("congo basin", "congo", "africa")),
    Place("Danum Valley", "Malaysia", "Tropical moist broadleaf", 117.80, 4.96, 0.35,
          demo=True, note="Old-growth lowland dipterocarp forest in Sabah, Borneo",
          aliases=("borneo", "sabah", "dipterocarp")),
    Place("Leuser Ecosystem", "Indonesia", "Tropical moist broadleaf", 97.40, 3.60, 0.8,
          demo=True, note="Northern Sumatra — active clearing frontier at the forest margin",
          aliases=("sumatra", "indonesia", "aceh", "gunung leuser")),
    Place("Western Ghats — Silent Valley", "India", "Tropical moist broadleaf", 76.44, 11.09, 0.3,
          demo=True, note="Evergreen montane forest, Kerala",
          aliases=("western ghats", "kerala", "india", "silent valley")),
    Place("Tongass National Forest", "United States", "Temperate coniferous", -134.20, 57.40, 1.2,
          demo=True, note="Largest temperate rainforest in North America",
          aliases=("alaska", "usa", "temperate rainforest")),
    Place("Białowieża Forest", "Poland / Belarus", "Temperate broadleaf", 23.80, 52.72, 0.4,
          demo=True, note="Last large primeval lowland forest in Europe",
          aliases=("bialowieza", "europe", "primeval")),

    # --- Amazon basin -----------------------------------------------------
    Place("Manaus", "Brazil", "Tropical moist broadleaf", -60.02, -3.12, 0.6,
          aliases=("amazon", "amazonia", "rio negro", "brasil")),
    Place("Xingu Indigenous Park", "Brazil", "Tropical moist broadleaf", -53.10, -11.60, 1.2,
          aliases=("amazon", "amazonia", "brasil")),
    Place("Yasuní National Park", "Ecuador", "Tropical moist broadleaf", -76.20, -0.90, 0.8,
          aliases=("amazon", "amazonia", "yasuni")),
    Place("Madre de Dios", "Peru", "Tropical moist broadleaf", -69.70, -12.30, 1.0,
          aliases=("amazon", "amazonia", "peru")),
    Place("Chiribiquete", "Colombia", "Tropical moist broadleaf", -72.70, 0.60, 1.0,
          aliases=("amazon", "amazonia", "colombia")),
    Place("Rondônia deforestation arc", "Brazil", "Tropical moist broadleaf", -62.50, -10.50, 1.2,
          aliases=("amazon", "amazonia", "rondonia", "brasil")),
    Place("Iwokrama Forest", "Guyana", "Tropical moist broadleaf", -58.90, 4.50, 0.6,
          aliases=("amazon", "guiana shield")),

    # --- Congo basin -------------------------------------------------------
    Place("Odzala-Kokoua", "Republic of the Congo", "Tropical moist broadleaf", 14.90, 0.90, 0.7,
          aliases=("congo basin", "congo", "africa")),
    Place("Lopé National Park", "Gabon", "Tropical moist broadleaf", 11.60, -0.50, 0.6,
          aliases=("congo basin", "gabon", "lope", "africa")),
    Place("Dzanga-Sangha", "Central African Republic", "Tropical moist broadleaf", 16.20, 2.90, 0.5,
          aliases=("congo basin", "africa")),
    Place("Korup National Park", "Cameroon", "Tropical moist broadleaf", 8.85, 5.10, 0.4,
          aliases=("congo basin", "africa")),
    Place("Ituri Forest", "DR Congo", "Tropical moist broadleaf", 28.60, 1.40, 0.9,
          aliases=("congo basin", "congo", "africa")),

    # --- Southeast Asia -----------------------------------------------------
    Place("Taman Negara", "Malaysia", "Tropical moist broadleaf", 102.40, 4.55, 0.5,
          aliases=("peninsular malaysia",)),
    Place("Kinabatangan", "Malaysia", "Tropical moist broadleaf", 118.30, 5.45, 0.4,
          aliases=("borneo", "sabah")),
    Place("Tanjung Puting", "Indonesia", "Tropical peat swamp", 111.90, -2.80, 0.5,
          aliases=("borneo", "kalimantan", "peatland")),
    Place("Lorentz National Park", "Indonesia", "Tropical montane", 137.80, -4.40, 1.0,
          aliases=("papua", "new guinea")),
    Place("Khao Yai", "Thailand", "Tropical moist broadleaf", 101.40, 14.44, 0.4),
    Place("Cat Tien National Park", "Vietnam", "Tropical moist broadleaf", 107.40, 11.42, 0.3,
          aliases=("mekong",)),

    # --- South Asia ----------------------------------------------------------
    Place("Sundarbans", "India / Bangladesh", "Mangrove", 89.10, 21.95, 0.8,
          aliases=("mangrove", "bengal", "india", "bangladesh")),
    Place("Nagarhole National Park", "India", "Tropical dry broadleaf", 76.10, 12.05, 0.4,
          aliases=("western ghats", "karnataka", "india")),
    Place("Namdapha National Park", "India", "Tropical montane", 96.40, 27.50, 0.5,
          aliases=("arunachal", "india", "himalaya")),
    Place("Simlipal", "India", "Tropical moist deciduous", 86.35, 21.90, 0.4,
          aliases=("odisha", "india")),
    Place("Chitwan National Park", "Nepal", "Subtropical moist broadleaf", 84.35, 27.52, 0.4,
          aliases=("himalaya", "terai")),
    Place("Sinharaja Forest", "Sri Lanka", "Tropical moist broadleaf", 80.45, 6.40, 0.2,
          aliases=("sri lanka",)),

    # --- Temperate -----------------------------------------------------------
    Place("Olympic National Park", "United States", "Temperate rainforest", -123.50, 47.80, 0.7,
          aliases=("usa", "pacific northwest")),
    Place("Redwood National Park", "United States", "Temperate coniferous", -124.00, 41.30, 0.4,
          aliases=("usa", "california", "sequoia")),
    Place("Great Smoky Mountains", "United States", "Temperate broadleaf", -83.50, 35.60, 0.6,
          aliases=("usa", "appalachia")),
    Place("Algonquin Provincial Park", "Canada", "Temperate mixed", -78.40, 45.60, 0.8,
          aliases=("ontario", "canada")),
    Place("Black Forest", "Germany", "Temperate mixed", 8.20, 48.30, 0.6,
          aliases=("schwarzwald", "europe")),
    Place("Carpathian primeval beech", "Romania / Ukraine", "Temperate broadleaf", 24.60, 47.80, 0.8,
          aliases=("carpathians", "europe")),
    Place("Valdivian temperate rainforest", "Chile", "Temperate rainforest", -72.40, -40.20, 0.9,
          aliases=("patagonia", "chile")),
    Place("Tasmanian Wilderness", "Australia", "Temperate rainforest", 146.20, -42.30, 0.9,
          aliases=("tasmania", "australia")),
    Place("Fiordland National Park", "New Zealand", "Temperate rainforest", 167.50, -45.20, 0.9,
          aliases=("new zealand", "aotearoa")),
    Place("Shirakami-Sanchi", "Japan", "Temperate broadleaf", 140.15, 40.45, 0.4,
          aliases=("japan", "beech")),
    Place("Jiuzhaigou", "China", "Temperate coniferous", 103.90, 33.20, 0.4,
          aliases=("china", "sichuan")),

    # --- Boreal (note: beyond the GEDI latitude limit) -----------------------
    Place("Taiga Plains", "Canada", "Boreal", -118.00, 61.50, 1.5,
          note="Beyond the GEDI 51.6° limit — no local biomass calibration available",
          aliases=("boreal", "taiga", "canada")),
    Place("Wood Buffalo National Park", "Canada", "Boreal", -113.00, 59.40, 1.2,
          note="Beyond the GEDI 51.6° limit",
          aliases=("boreal", "taiga", "canada")),
    Place("Lapland", "Finland", "Boreal", 26.50, 67.80, 1.5,
          note="Beyond the GEDI 51.6° limit",
          aliases=("boreal", "taiga", "finland", "scandinavia")),
    Place("Taiga Shield", "Russia", "Boreal", 95.00, 62.00, 2.0,
          note="Beyond the GEDI 51.6° limit",
          aliases=("boreal", "taiga", "siberia", "russia")),

    # --- Dry forest & mangrove -----------------------------------------------
    Place("Miombo woodland", "Zambia", "Tropical dry broadleaf", 27.50, -13.50, 1.2,
          aliases=("miombo", "africa", "dry forest")),
    Place("Gran Chaco", "Paraguay / Argentina", "Dry forest", -60.50, -22.50, 1.5,
          aliases=("chaco", "dry forest")),
    Place("Caatinga", "Brazil", "Dry forest", -40.50, -9.50, 1.5,
          aliases=("dry forest", "brasil")),
    Place("Niombato mangroves", "Senegal", "Mangrove", -16.50, 13.70, 0.4,
          aliases=("mangrove", "africa", "sine saloum")),
    Place("Bijagós mangroves", "Guinea-Bissau", "Mangrove", -15.90, 11.30, 0.5,
          aliases=("mangrove", "africa")),
    Place("Madagascar eastern rainforest", "Madagascar", "Tropical moist broadleaf", 48.80, -18.90, 0.9,
          aliases=("madagascar",)),
    Place("Atlantic Forest — Serra do Mar", "Brazil", "Tropical moist broadleaf", -45.20, -23.40, 0.7,
          aliases=("mata atlantica", "atlantic forest", "brasil")),
)


#: Latin letters that NFKD does not decompose into base + combining mark.
_SPECIAL_FOLD = str.maketrans(
    {"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D",
     "ı": "i", "ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "ð": "d", "þ": "th"}
)


def _fold(text: str) -> str:
    """Case- and accent-insensitive key for matching."""
    normalised = unicodedata.normalize("NFKD", text.translate(_SPECIAL_FOLD))
    return "".join(c for c in normalised if not unicodedata.combining(c)).casefold()


_INDEX = [
    (
        _fold(" ".join((p.name, p.country, p.biome, *p.aliases))),
        _fold(p.name),
        p,
    )
    for p in PLACES
]


def search(query: str, limit: int = 8) -> list[Place]:
    """Rank places by how well they match the query."""
    needle = _fold(query.strip())
    if not needle:
        return []

    scored: list[tuple[int, int, Place]] = []
    for haystack, name_key, place in _INDEX:
        if name_key.startswith(needle):
            rank = 0
        elif needle in name_key:
            rank = 1
        elif haystack.startswith(needle):
            rank = 2
        elif needle in haystack:
            rank = 3
        elif all(token in haystack for token in needle.split()):
            rank = 4
        else:
            continue
        scored.append((rank, len(place.name), place))

    scored.sort(key=lambda item: (item[0], item[1], item[2].name))
    return [place for _, _, place in scored[:limit]]


def demo_places() -> list[Place]:
    return [p for p in PLACES if p.demo]
