"""Geographic data for US diaspora and Haiti locations."""

import math
import random
from typing import NamedTuple


class Location(NamedTuple):
    city: str
    state_or_department: str
    country: str
    country_code: str
    latitude: float
    longitude: float


US_DIASPORA_LOCATIONS = [
    Location("Boston", "MA", "United States", "US", 42.3601, -71.0589),
    Location("Miami", "FL", "United States", "US", 25.7617, -80.1918),
    Location("Fort Lauderdale", "FL", "United States", "US", 26.1224, -80.1373),
    Location("New York", "NY", "United States", "US", 40.7128, -74.0060),
    Location("Brooklyn", "NY", "United States", "US", 40.6782, -73.9442),
    Location("Newark", "NJ", "United States", "US", 40.7357, -74.1724),
    Location("Orlando", "FL", "United States", "US", 28.5383, -81.3792),
    Location("Atlanta", "GA", "United States", "US", 33.7490, -84.3880),
    Location("Chicago", "IL", "United States", "US", 41.8781, -87.6298),
    Location("Los Angeles", "CA", "United States", "US", 34.0522, -118.2437),
    Location("Stamford", "CT", "United States", "US", 41.0534, -73.5387),
    Location("Spring Valley", "NY", "United States", "US", 41.1132, -74.0438),
]

HAITI_LOCATIONS = [
    Location("Port-au-Prince", "Ouest", "Haiti", "HT", 18.5944, -72.3074),
    Location("Cap-Haitien", "Nord", "Haiti", "HT", 19.7578, -72.2044),
    Location("Gonaives", "Artibonite", "Haiti", "HT", 19.4502, -72.6888),
    Location("Les Cayes", "Sud", "Haiti", "HT", 18.1940, -73.7504),
    Location("Jacmel", "Sud-Est", "Haiti", "HT", 18.2340, -72.5353),
    Location("Jeremie", "Grand'Anse", "Haiti", "HT", 18.6500, -74.1167),
    Location("Hinche", "Centre", "Haiti", "HT", 19.1453, -72.0093),
    Location("Port-de-Paix", "Nord-Ouest", "Haiti", "HT", 19.9397, -72.8322),
    Location("Miragoane", "Nippes", "Haiti", "HT", 18.4449, -73.0883),
    Location("Petit-Goave", "Ouest", "Haiti", "HT", 18.4317, -72.8683),
    Location("Saint-Marc", "Artibonite", "Haiti", "HT", 19.1078, -72.6983),
]


def random_us_location() -> Location:
    return random.choice(US_DIASPORA_LOCATIONS)


def random_haiti_location() -> Location:
    return random.choice(HAITI_LOCATIONS)


def location_to_geo(location: Location) -> dict:
    return {
        "latitude": location.latitude,
        "longitude": location.longitude,
        "country": location.country_code,
        "city": location.city,
    }


def jitter_coordinates(lat: float, lng: float, radius_km: float = 5.0) -> tuple[float, float]:
    angle = random.uniform(0, 2 * math.pi)
    distance = random.uniform(0, radius_km) / 111.0
    return lat + distance * math.cos(angle), lng + distance * math.sin(angle)
