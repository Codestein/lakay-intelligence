"""Statistical distribution helpers for realistic data generation."""

import random
import uuid
from datetime import datetime


def log_normal_sample(
    mean: float, std: float, min_val: float = 0.01, max_val: float | None = None
) -> float:
    value = random.lognormvariate(mean, std)
    value = max(value, min_val)
    if max_val is not None:
        value = min(value, max_val)
    return value


def weighted_amount(
    common_amounts: list[float], common_prob: float, random_mean: float, random_std: float
) -> float:
    if random.random() < common_prob:
        return float(random.choice(common_amounts))
    return max(10.0, random.gauss(random_mean, random_std))


def poisson_interval(rate_per_hour: float) -> float:
    if rate_per_hour <= 0:
        return 3600.0
    return random.expovariate(rate_per_hour / 3600.0)


def is_business_hours(dt: datetime) -> bool:
    return 8 <= dt.hour <= 22


def is_weekend(dt: datetime) -> bool:
    return dt.weekday() >= 5


def seasonal_multiplier(dt: datetime) -> float:
    month, day = dt.month, dt.day
    if (month == 12 and day >= 15) or (month == 1 and day <= 7):
        return 2.5
    if month == 2 and 10 <= day <= 20:
        return 1.8
    if month == 4 and 1 <= day <= 15:
        return 1.5
    if month == 9:
        return 1.3
    if month in (6, 7):
        return 0.8
    return 1.0


def generate_ip_address() -> str:
    octets = [
        random.randint(10, 99), random.randint(0, 255),
        random.randint(0, 255), random.randint(1, 254),
    ]
    return f"{octets[0]}.{octets[1]}.{octets[2]}.{octets[3]}"


def generate_device_id() -> str:
    return f"device_{uuid.UUID(int=random.getrandbits(128), version=4).hex[:16]}"
