"""Concrete fraud detection rules."""

import math
from abc import ABC, abstractmethod

from .models import RiskFactor, RuleResult, TransactionFeatures

EARTH_RADIUS_KM = 6371.0


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in km between two lat/lon points."""
    lat1_r, lon1_r = math.radians(lat1), math.radians(lon1)
    lat2_r, lon2_r = math.radians(lat2), math.radians(lon2)
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


class FraudRule(ABC):
    @abstractmethod
    def evaluate(self, amount: float, features: TransactionFeatures) -> RuleResult:
        ...


class HighAmountRule(FraudRule):
    def evaluate(self, amount: float, features: TransactionFeatures) -> RuleResult:
        if amount < 5000:
            return RuleResult(rule_name="high_amount", triggered=False)
        # Scale 10-40 for amounts $5k-$50k+
        score = min(10 + (amount - 5000) / 1500, 40)
        return RuleResult(
            rule_name="high_amount",
            triggered=True,
            score=score,
            risk_factor=RiskFactor.HIGH_AMOUNT,
            details=f"High amount: ${amount:,.2f}",
        )


class StructuringNear3kRule(FraudRule):
    def evaluate(self, amount: float, features: TransactionFeatures) -> RuleResult:
        if not (2800 <= amount <= 2999):
            return RuleResult(rule_name="structuring_near_3k", triggered=False)
        # Closer to $3k = higher score (25-40)
        proximity = (amount - 2800) / 199
        score = 25 + proximity * 15
        return RuleResult(
            rule_name="structuring_near_3k",
            triggered=True,
            score=score,
            risk_factor=RiskFactor.STRUCTURING_NEAR_3K,
            details=f"Structuring near $3k: ${amount:,.2f}",
        )


class StructuringNear10kRule(FraudRule):
    def evaluate(self, amount: float, features: TransactionFeatures) -> RuleResult:
        if not (9500 <= amount <= 9999):
            return RuleResult(rule_name="structuring_near_10k", triggered=False)
        # Closer to $10k = higher score (30-50)
        proximity = (amount - 9500) / 499
        score = 30 + proximity * 20
        return RuleResult(
            rule_name="structuring_near_10k",
            triggered=True,
            score=score,
            risk_factor=RiskFactor.STRUCTURING_NEAR_10K,
            details=f"Structuring near $10k: ${amount:,.2f}",
        )


class VelocityCount1hRule(FraudRule):
    def evaluate(self, amount: float, features: TransactionFeatures) -> RuleResult:
        if features.velocity_count_1h < 5:
            return RuleResult(rule_name="velocity_count_1h", triggered=False)
        # Scale 15-50 for 5-15+ txns in 1h
        score = min(15 + (features.velocity_count_1h - 5) * 3.5, 50)
        return RuleResult(
            rule_name="velocity_count_1h",
            triggered=True,
            score=score,
            risk_factor=RiskFactor.VELOCITY_COUNT_1H,
            details=f"{features.velocity_count_1h} transactions in last hour",
        )


class VelocityCount24hRule(FraudRule):
    def evaluate(self, amount: float, features: TransactionFeatures) -> RuleResult:
        if features.velocity_count_24h < 20:
            return RuleResult(rule_name="velocity_count_24h", triggered=False)
        # Scale 15-40 for 20-30+ txns in 24h
        score = min(15 + (features.velocity_count_24h - 20) * 2.5, 40)
        return RuleResult(
            rule_name="velocity_count_24h",
            triggered=True,
            score=score,
            risk_factor=RiskFactor.VELOCITY_COUNT_24H,
            details=f"{features.velocity_count_24h} transactions in last 24h",
        )


class VelocityAmount24hRule(FraudRule):
    def evaluate(self, amount: float, features: TransactionFeatures) -> RuleResult:
        total = features.velocity_amount_24h + amount
        if total < 10000:
            return RuleResult(rule_name="velocity_amount_24h", triggered=False)
        # Scale 15-45 for $10k-$50k+
        score = min(15 + (total - 10000) / 1333, 45)
        return RuleResult(
            rule_name="velocity_amount_24h",
            triggered=True,
            score=score,
            risk_factor=RiskFactor.VELOCITY_AMOUNT_24H,
            details=f"24h total: ${total:,.2f}",
        )


class NewDeviceRule(FraudRule):
    def evaluate(self, amount: float, features: TransactionFeatures) -> RuleResult:
        if not features.is_new_device:
            return RuleResult(rule_name="new_device", triggered=False)
        return RuleResult(
            rule_name="new_device",
            triggered=True,
            score=15,
            risk_factor=RiskFactor.NEW_DEVICE,
            details="Transaction from previously unseen device",
        )


class NewGeolocationRule(FraudRule):
    def evaluate(self, amount: float, features: TransactionFeatures) -> RuleResult:
        if not features.is_new_country:
            return RuleResult(rule_name="new_geolocation", triggered=False)
        return RuleResult(
            rule_name="new_geolocation",
            triggered=True,
            score=20,
            risk_factor=RiskFactor.NEW_GEOLOCATION,
            details="Transaction from previously unseen country",
        )


class ImpossibleTravelRule(FraudRule):
    MAX_SPEED_KMH = 900

    def evaluate(self, amount: float, features: TransactionFeatures) -> RuleResult:
        if (
            features.last_geo_location is None
            or features.time_since_last_txn_seconds is None
            or features.time_since_last_txn_seconds <= 0
        ):
            return RuleResult(rule_name="impossible_travel", triggered=False)

        current_lat = features.last_geo_location.get("current_lat")
        current_lon = features.last_geo_location.get("current_lon")
        prev_lat = features.last_geo_location.get("prev_lat")
        prev_lon = features.last_geo_location.get("prev_lon")

        if any(v is None for v in [current_lat, current_lon, prev_lat, prev_lon]):
            return RuleResult(rule_name="impossible_travel", triggered=False)

        distance_km = haversine(prev_lat, prev_lon, current_lat, current_lon)
        hours = features.time_since_last_txn_seconds / 3600
        speed_kmh = distance_km / hours if hours > 0 else float("inf")

        if speed_kmh <= self.MAX_SPEED_KMH:
            return RuleResult(rule_name="impossible_travel", triggered=False)

        return RuleResult(
            rule_name="impossible_travel",
            triggered=True,
            score=35,
            risk_factor=RiskFactor.IMPOSSIBLE_TRAVEL,
            details=f"Impossible travel: {distance_km:.0f}km in {hours:.2f}h ({speed_kmh:.0f}km/h)",
        )


class UnusualHourRule(FraudRule):
    def evaluate(self, amount: float, features: TransactionFeatures) -> RuleResult:
        # This rule is evaluated by the caller using initiated_at hour
        # We use a sentinel: if the caller sets velocity_count_1h to trigger via features,
        # or we can check via a simple convention.
        # Actually, this rule needs the hour. We'll check via a convention:
        # The features don't carry the hour, so this rule is always evaluated
        # externally. But to keep the interface consistent, we'll pass the hour
        # encoded in features. Let's just return not triggered by default
        # and let the rules engine call it with the hour directly.
        return RuleResult(rule_name="unusual_hour", triggered=False)


class UnusualHourEvaluator:
    """Separate evaluator since hour info isn't in TransactionFeatures."""

    @staticmethod
    def evaluate(hour_utc: int) -> RuleResult:
        if 2 <= hour_utc < 5:
            return RuleResult(
                rule_name="unusual_hour",
                triggered=True,
                score=10,
                risk_factor=RiskFactor.UNUSUAL_HOUR,
                details=f"Transaction at unusual hour: {hour_utc}:00 UTC",
            )
        return RuleResult(rule_name="unusual_hour", triggered=False)


ALL_RULES: list[FraudRule] = [
    HighAmountRule(),
    StructuringNear3kRule(),
    StructuringNear10kRule(),
    VelocityCount1hRule(),
    VelocityCount24hRule(),
    VelocityAmount24hRule(),
    NewDeviceRule(),
    NewGeolocationRule(),
    ImpossibleTravelRule(),
    UnusualHourRule(),
]
