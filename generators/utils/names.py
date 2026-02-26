"""Haitian name generator for realistic synthetic data."""

import random

FIRST_NAMES = [
    "Jean",
    "Marie",
    "Pierre",
    "Joseph",
    "Rose",
    "Jacques",
    "Francois",
    "Anne",
    "Paul",
    "Michel",
    "Yvette",
    "Claude",
    "Edwidge",
    "Fritz",
    "Guerda",
    "Manno",
    "Nathalie",
    "Roland",
    "Sophia",
    "Wyclef",
    "Daphne",
    "Emmanuel",
    "Fabienne",
    "Gerard",
    "Islande",
    "Jocelyn",
    "Ketly",
    "Luckner",
    "Mireille",
    "Nadine",
    "Reginald",
    "Stephanie",
    "Thierry",
    "Widline",
    "Yves",
    "Bernadette",
    "Charles",
    "Daniella",
    "Evens",
    "Gaelle",
    "Henri",
    "Josette",
    "Karl",
    "Lovely",
    "Mackenson",
]

LAST_NAMES = [
    "Jean-Baptiste",
    "Pierre",
    "Auguste",
    "Desrosiers",
    "Thermidor",
    "Celestin",
    "Etienne",
    "Francois",
    "Guillaume",
    "Hyppolite",
    "Innocent",
    "Janvier",
    "Kenol",
    "Lafortune",
    "Milfort",
    "Nicolas",
    "Olivier",
    "Petit-Frere",
    "Remy",
    "Saint-Louis",
    "Toussaint",
    "Vilmenay",
    "Wagnac",
    "Alexandre",
    "Baptiste",
    "Casimir",
    "Dorcely",
    "Estime",
    "Fils-Aime",
    "Guerrier",
    "Louis-Jean",
    "Morisseau",
    "Noel",
    "Philippe",
]


def random_name() -> tuple[str, str]:
    return random.choice(FIRST_NAMES), random.choice(LAST_NAMES)


def random_full_name() -> str:
    first, last = random_name()
    return f"{first} {last}"


def random_email(first_name: str, last_name: str) -> str:
    domains = ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com"]
    separator = random.choice([".", "_", ""])
    number = str(random.randint(1, 999)) if random.random() < 0.5 else ""
    clean_last = last_name.lower().replace("-", "")
    return f"{first_name.lower()}{separator}{clean_last}{number}@{random.choice(domains)}"


def random_phone(country: str = "US") -> str:
    if country == "US":
        area_codes = ["617", "305", "786", "718", "212", "347", "973", "407", "404", "312", "203"]
        return f"+1{random.choice(area_codes)}{random.randint(2000000, 9999999)}"
    elif country == "HT":
        prefixes = ["34", "36", "37", "38", "39", "40", "41", "42", "46", "47", "48", "49"]
        return f"+509{random.choice(prefixes)}{random.randint(100000, 999999)}"
    return f"+1{random.randint(2000000000, 9999999999)}"
