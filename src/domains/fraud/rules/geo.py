"""Geography-based fraud detection rules."""

import math

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import RawEvent

from ..config import FraudConfig
from ..models import FraudScoreRequest, RiskFactor, RuleResult, TransactionFeatures
from .base import FraudRule

EARTH_RADIUS_KM = 6371.0


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in km between two lat/lon points."""
    lat1_r, lon1_r = math.radians(lat1), math.radians(lon1)
    lat2_r, lon2_r = math.radians(lat2), math.radians(lon2)
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


class ImpossibleTravelRule(FraudRule):
    """Triggers when travel speed between consecutive events exceeds threshold."""

    rule_id = "impossible_travel"
    category = "geo"
    default_weight = 0.20

    async def evaluate(
        self,
        request: FraudScoreRequest,
        features: TransactionFeatures,
        session: AsyncSession,
        config: FraudConfig,
    ) -> RuleResult:
        if (
            features.last_geo_location is None
            or features.time_since_last_txn_seconds is None
            or features.time_since_last_txn_seconds <= 0
        ):
            return self._not_triggered()

        current_lat = features.last_geo_location.get("current_lat")
        current_lon = features.last_geo_location.get("current_lon")
        prev_lat = features.last_geo_location.get("prev_lat")
        prev_lon = features.last_geo_location.get("prev_lon")

        if any(v is None for v in [current_lat, current_lon, prev_lat, prev_lon]):
            return self._not_triggered()

        distance_km = haversine(prev_lat, prev_lon, current_lat, current_lon)
        hours = features.time_since_last_txn_seconds / 3600
        speed_kmh = distance_km / hours if hours > 0 else float("inf")

        max_speed = config.geo.impossible_travel_speed_kmh
        if speed_kmh <= max_speed:
            return self._not_triggered()

        # Higher score for more extreme speeds
        ratio = min(speed_kmh / max_speed, 5.0)
        score = min(0.5 + (ratio - 1.0) * 0.125, 1.0)

        return self._triggered(
            score=score,
            risk_factor=RiskFactor.IMPOSSIBLE_TRAVEL,
            details=f"Impossible travel: {distance_km:.0f}km in {hours:.2f}h ({speed_kmh:.0f}km/h)",
            severity="critical",
            confidence=0.95,
            evidence={
                "distance_km": distance_km,
                "hours": hours,
                "speed_kmh": speed_kmh,
                "max_speed_kmh": max_speed,
            },
        )


class NewGeographyRule(FraudRule):
    """Triggers when activity comes from an unseen country."""

    rule_id = "new_geography"
    category = "geo"
    default_weight = 0.10

    async def evaluate(
        self,
        request: FraudScoreRequest,
        features: TransactionFeatures,
        session: AsyncSession,
        config: FraudConfig,
    ) -> RuleResult:
        if not features.is_new_country:
            return self._not_triggered()

        country = "unknown"
        if request.geo_location:
            country = request.geo_location.get("country", "unknown")

        return self._triggered(
            score=0.4,
            risk_factor=RiskFactor.NEW_GEOLOCATION,
            details=f"Activity from previously unseen country: {country}",
            severity="medium",
            confidence=0.70,
            evidence={"country": country, "unique_countries_7d": features.unique_countries_7d},
        )


class ThirdCountrySenderRule(FraudRule):
    """Triggers when a US-based user transacts from a non-US/non-HT country.

    Corridor-aware: Trebanx primarily serves US<->Haiti corridor.
    """

    rule_id = "third_country_sender"
    category = "geo"
    default_weight = 0.15

    async def evaluate(
        self,
        request: FraudScoreRequest,
        features: TransactionFeatures,
        session: AsyncSession,
        config: FraudConfig,
    ) -> RuleResult:
        if not request.geo_location:
            return self._not_triggered()

        current_country = request.geo_location.get("country")
        if not current_country:
            return self._not_triggered()

        home_countries = config.geo.home_countries

        # If transacting from a home country, no issue
        if current_country in home_countries:
            return self._not_triggered()

        # Check if user has historically been in home countries
        stmt = select(
            func.distinct(RawEvent.payload["payload"]["geo_location"]["country"].astext)
        ).where(
            RawEvent.payload["payload"]["user_id"].astext == request.user_id,
            RawEvent.payload["payload"]["geo_location"]["country"].astext.isnot(None),
        )
        result = await session.execute(stmt)
        known_countries = {row[0] for row in result.fetchall()}

        # If user has history only in home countries but now in a third country
        has_home_history = bool(known_countries & set(home_countries))
        if not has_home_history:
            return self._not_triggered()

        return self._triggered(
            score=0.5,
            risk_factor=RiskFactor.THIRD_COUNTRY_SENDER,
            details=f"Home-corridor user transacting from {current_country}",
            severity="high",
            confidence=0.80,
            evidence={
                "current_country": current_country,
                "home_countries": list(home_countries),
                "known_countries": list(known_countries),
            },
        )


class NewDeviceRule(FraudRule):
    """Triggers when transaction comes from a previously unseen device."""

    rule_id = "new_device"
    category = "geo"
    default_weight = 0.08

    async def evaluate(
        self,
        request: FraudScoreRequest,
        features: TransactionFeatures,
        session: AsyncSession,
        config: FraudConfig,
    ) -> RuleResult:
        if not features.is_new_device:
            return self._not_triggered()

        return self._triggered(
            score=0.3,
            risk_factor=RiskFactor.NEW_DEVICE,
            details="Transaction from previously unseen device",
            severity="low",
            confidence=0.60,
            evidence={"device_id": request.device_id, "unique_devices_7d": features.unique_devices_7d},
        )
