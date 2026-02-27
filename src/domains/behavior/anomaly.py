"""Session anomaly scoring engine (Phase 7, Task 7.2).

Compares each session against the user's behavioral profile across five
independent dimensions: temporal, device, geographic, behavioral, and
engagement. Produces a composite 0.0–1.0 anomaly score with classification
and recommended action.
"""

import math
from datetime import UTC, datetime
from typing import Any

import structlog

from src.features.store import FeatureStore

from .config import BehaviorConfig, default_config
from .models import (
    AnomalyClassification,
    DimensionAnomalyScore,
    ProfileStatus,
    RecommendedAction,
    SessionAnomalyResult,
    UserBehaviorProfile,
)

logger = structlog.get_logger()

EARTH_RADIUS_KM = 6371.0


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in km between two lat/lon points."""
    lat1_r, lon1_r = math.radians(lat1), math.radians(lon1)
    lat2_r, lon2_r = math.radians(lat2), math.radians(lon2)
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


class SessionAnomalyScorer:
    """Scores sessions across multiple anomaly dimensions."""

    def __init__(
        self,
        config: BehaviorConfig | None = None,
        feature_store: FeatureStore | None = None,
    ) -> None:
        self._config = config or default_config
        self._feature_store = feature_store or FeatureStore()

    async def score_session(
        self,
        session_event: dict[str, Any],
        profile: UserBehaviorProfile | None,
        feast_features: dict[str, Any] | None = None,
    ) -> SessionAnomalyResult:
        """Score a session against the user's behavioral profile.

        Args:
            session_event: The session event data.
            profile: The user's behavioral profile (None if no profile exists).
            feast_features: Override Feast features for testing.

        Returns:
            SessionAnomalyResult with composite score and dimension breakdown.
        """
        user_id = session_event.get("user_id", "unknown")
        session_id = session_event.get("session_id", "unknown")
        now = datetime.now(UTC)

        # Fetch Feast features if not provided
        if feast_features is None:
            feast_features = await self._feature_store.get_features(user_id, "behavior")

        weights = self._config.anomaly_weights
        thresholds = self._config.anomaly_thresholds

        # Compute each dimension score
        temporal_score = self._score_temporal(session_event, profile, feast_features)
        device_score = self._score_device(session_event, profile, feast_features)
        geographic_score = self._score_geographic(session_event, profile, feast_features)
        behavioral_score = self._score_behavioral(session_event, profile, feast_features)
        engagement_score = self._score_engagement(session_event, profile, feast_features)

        dimension_scores = [
            temporal_score,
            device_score,
            geographic_score,
            behavioral_score,
            engagement_score,
        ]

        # Weighted composite
        composite = (
            temporal_score.score * weights.temporal
            + device_score.score * weights.device
            + geographic_score.score * weights.geographic
            + behavioral_score.score * weights.behavioral
            + engagement_score.score * weights.engagement
        )

        # Apply profile maturity adjustments
        profile_maturity = 0
        if profile:
            profile_maturity = profile.profile_maturity
            if profile.profile_status == ProfileStatus.BUILDING:
                # Reduce composite for immature profiles (higher thresholds)
                composite *= 0.6
            elif profile.profile_status == ProfileStatus.STALE:
                # Slightly reduce for stale profiles
                composite *= 0.8

        composite = _clamp(composite)

        # Classify
        classification = self._classify(composite, thresholds)
        recommended_action = self._recommend_action(classification)

        result = SessionAnomalyResult(
            session_id=session_id,
            user_id=user_id,
            composite_score=round(composite, 4),
            classification=classification,
            dimension_scores=dimension_scores,
            profile_maturity=profile_maturity,
            recommended_action=recommended_action,
            timestamp=now,
        )

        logger.info(
            "session_anomaly_scored",
            session_id=session_id,
            user_id=user_id,
            composite_score=result.composite_score,
            classification=classification.value,
            profile_maturity=profile_maturity,
        )

        return result

    def _score_temporal(
        self,
        session_event: dict[str, Any],
        profile: UserBehaviorProfile | None,
        features: dict[str, Any],
    ) -> DimensionAnomalyScore:
        """Score temporal anomaly: how unusual is the login time?"""
        thresholds = self._config.anomaly_thresholds

        # Use Feast feature if available
        hour_deviation = features.get("current_session_hour_deviation")
        typical_hour_mean = features.get("typical_login_hour_mean")
        typical_hour_std = features.get("typical_login_hour_std")

        session_start = session_event.get("session_start")
        if session_start and isinstance(session_start, str):
            session_start = datetime.fromisoformat(session_start)

        # If we have the deviation from Feast, use it directly
        if hour_deviation is not None and typical_hour_std and typical_hour_std > 0:
            zscore = abs(hour_deviation) / typical_hour_std
        elif session_start and profile and profile.temporal_baseline.typical_hours:
            # Compute deviation from profile
            session_hour = session_start.hour
            hour_freq = profile.temporal_baseline.typical_hours
            if hour_freq:
                # Check if this hour has any frequency
                freq = hour_freq.get(session_hour, 0.0)
                max_freq = max(hour_freq.values()) if hour_freq else 1.0
                # Low frequency = high anomaly
                if max_freq > 0:
                    zscore = (1.0 - freq / max_freq) * thresholds.temporal_zscore_critical
                else:
                    zscore = 0.0
            else:
                zscore = 0.0
        else:
            # No profile or features — cannot assess
            return DimensionAnomalyScore(
                dimension="temporal", score=0.0, details="Insufficient data for temporal scoring"
            )

        # Map z-score to 0-1 score
        if zscore <= 1.0:
            score = 0.0
        elif zscore <= thresholds.temporal_zscore_high:
            score = (zscore - 1.0) / (thresholds.temporal_zscore_high - 1.0) * 0.5
        elif zscore <= thresholds.temporal_zscore_critical:
            score = 0.5 + (zscore - thresholds.temporal_zscore_high) / (
                thresholds.temporal_zscore_critical - thresholds.temporal_zscore_high
            ) * 0.5
        else:
            score = 1.0

        details = f"Temporal z-score: {zscore:.2f}"
        if session_start:
            details += f", session hour: {session_start.hour}"

        return DimensionAnomalyScore(
            dimension="temporal", score=_clamp(score), details=details
        )

    def _score_device(
        self,
        session_event: dict[str, Any],
        profile: UserBehaviorProfile | None,
        features: dict[str, Any],
    ) -> DimensionAnomalyScore:
        """Score device anomaly: is this a known device?"""
        thresholds = self._config.anomaly_thresholds

        device_id = session_event.get("device_id")
        device_type = session_event.get("device_type")
        new_device_flag = features.get("new_device_flag", False)
        distinct_devices = features.get("distinct_devices_30d", 1)

        if not device_id:
            return DimensionAnomalyScore(
                dimension="device", score=0.0, details="No device info"
            )

        score = 0.0
        details_parts = []

        # Check against profile
        is_known = False
        if profile and profile.device_baseline.known_devices:
            is_known = device_id in profile.device_baseline.known_devices

        if new_device_flag or not is_known:
            score = thresholds.new_device_score
            details_parts.append("New device detected")

            # Cross-platform switch boost (iOS -> Android or vice versa)
            if device_type and profile and profile.device_baseline.device_platforms:
                known_platforms = profile.device_baseline.device_platforms
                if device_type.lower() not in known_platforms and known_platforms:
                    score += thresholds.cross_platform_boost
                    details_parts.append(
                        f"Cross-platform switch: {known_platforms} -> {device_type}"
                    )

            # Device diversity context: if user normally uses many devices, less anomalous
            if distinct_devices and distinct_devices > 3:
                score *= 0.6  # reduce score for users who regularly switch devices
                details_parts.append(f"User uses {distinct_devices} devices regularly")
        else:
            details_parts.append("Known device")

        return DimensionAnomalyScore(
            dimension="device", score=_clamp(score), details="; ".join(details_parts)
        )

    def _score_geographic(
        self,
        session_event: dict[str, Any],
        profile: UserBehaviorProfile | None,
        features: dict[str, Any],
    ) -> DimensionAnomalyScore:
        """Score geographic anomaly: is this a known location? Impossible travel?"""
        thresholds = self._config.anomaly_thresholds

        geo = session_event.get("geo_location")
        if not geo:
            return DimensionAnomalyScore(
                dimension="geographic", score=0.0, details="No geo info"
            )

        current_city = geo.get("city", "unknown")
        current_country = geo.get("country", "unknown")
        current_lat = geo.get("lat") or geo.get("latitude")
        current_lon = geo.get("lon") or geo.get("longitude")

        score = 0.0
        details_parts = []

        # Check if location is known
        is_known_location = False
        if profile and profile.geographic_baseline.known_locations:
            for loc in profile.geographic_baseline.known_locations:
                if loc.get("city") == current_city and loc.get("country") == current_country:
                    is_known_location = True
                    break

        if not is_known_location:
            score = 0.4
            details_parts.append(f"New location: {current_city}, {current_country}")

            # Haiti corridor awareness: US <-> HT travel is normal for Trebanx users
            corridor_countries = thresholds.corridor_countries
            if current_country in corridor_countries:
                # Check if user's known locations are also in corridor
                if profile and profile.geographic_baseline.known_locations:
                    known_countries = {
                        loc.get("country") for loc in profile.geographic_baseline.known_locations
                    }
                    if known_countries & set(corridor_countries):
                        score *= (1.0 - thresholds.corridor_reduction)
                        details_parts.append("Haiti corridor travel (reduced anomaly)")
            elif profile and profile.geographic_baseline.known_locations:
                # Third country — not in the US/HT corridor
                known_countries = {
                    loc.get("country") for loc in profile.geographic_baseline.known_locations
                }
                if known_countries <= set(corridor_countries):
                    # User was exclusively in corridor, now in a third country
                    score = 0.7
                    details_parts.append(f"Third country: {current_country} (outside US/HT corridor)")

        # Impossible travel check
        max_travel_speed = features.get("max_travel_speed_24h")
        if max_travel_speed and max_travel_speed > thresholds.impossible_travel_speed_kmh:
            score = max(score, 0.9)
            details_parts.append(
                f"Impossible travel detected: {max_travel_speed:.0f} km/h"
            )
        elif current_lat is not None and current_lon is not None and profile:
            # Check against last known location from features
            last_country = features.get("last_known_country")
            last_city = features.get("last_known_city")
            if last_country and last_country != current_country:
                if not is_known_location:
                    score = max(score, 0.5)
                    details_parts.append(f"Country change: {last_country} -> {current_country}")

        if not details_parts:
            details_parts.append("Known location")

        return DimensionAnomalyScore(
            dimension="geographic", score=_clamp(score), details="; ".join(details_parts)
        )

    def _score_behavioral(
        self,
        session_event: dict[str, Any],
        profile: UserBehaviorProfile | None,
        features: dict[str, Any],
    ) -> DimensionAnomalyScore:
        """Score behavioral anomaly: session duration, actions, patterns."""
        thresholds = self._config.anomaly_thresholds

        duration = session_event.get("session_duration_seconds", 0.0)
        action_count = session_event.get("action_count", 0)
        actions = session_event.get("actions", [])

        score = 0.0
        details_parts = []

        # Use Feast features for baseline
        avg_duration = features.get("avg_session_duration_30d", 0.0)
        avg_actions = features.get("avg_actions_per_session_30d", 0.0)

        # Fall back to profile baselines
        if not avg_duration and profile:
            avg_duration = profile.session_baseline.avg_duration
        if not avg_actions and profile:
            avg_actions = profile.session_baseline.avg_actions

        std_duration = profile.session_baseline.std_duration if profile else 0.0
        std_actions = profile.session_baseline.std_actions if profile else 0.0

        # Duration anomaly (z-score)
        if avg_duration > 0 and std_duration > 0:
            dur_zscore = abs(duration - avg_duration) / std_duration
            if dur_zscore > thresholds.behavioral_zscore_high:
                dur_score = min(dur_zscore / (thresholds.behavioral_zscore_high * 2), 1.0)
                score = max(score, dur_score * 0.4)
                details_parts.append(f"Duration anomaly z={dur_zscore:.1f}")

        # Action count anomaly
        if avg_actions > 0 and std_actions > 0:
            act_zscore = abs(action_count - avg_actions) / std_actions
            if act_zscore > thresholds.behavioral_zscore_high:
                act_score = min(act_zscore / (thresholds.behavioral_zscore_high * 2), 1.0)
                score = max(score, act_score * 0.3)
                details_parts.append(f"Action count anomaly z={act_zscore:.1f}")

        # Action pattern anomaly: sensitive actions in unusual context
        sensitive_actions = self._config.ato.sensitive_actions
        sensitive_count = sum(1 for a in actions if a in sensitive_actions)
        if sensitive_count >= 2:
            # Multiple sensitive actions in one session
            score = max(score, min(sensitive_count * 0.2, 0.8))
            details_parts.append(f"{sensitive_count} sensitive actions in session")

        # Bot detection: actions per second
        if duration > 0 and action_count > 0:
            actions_per_sec = action_count / duration
            if actions_per_sec > thresholds.bot_actions_per_second:
                score = max(score, 0.7)
                details_parts.append(
                    f"Bot-like speed: {actions_per_sec:.1f} actions/sec"
                )

        if not details_parts:
            details_parts.append("Normal behavior pattern")

        return DimensionAnomalyScore(
            dimension="behavioral", score=_clamp(score), details="; ".join(details_parts)
        )

    def _score_engagement(
        self,
        session_event: dict[str, Any],
        profile: UserBehaviorProfile | None,
        features: dict[str, Any],
    ) -> DimensionAnomalyScore:
        """Score engagement anomaly: unusual feature usage, dormancy spikes."""
        thresholds = self._config.anomaly_thresholds

        days_since_login = features.get("days_since_last_login", 0)
        feature_breadth = features.get("feature_usage_breadth", 0.0)
        actions = session_event.get("actions", [])

        score = 0.0
        details_parts = []

        # Sudden activity after long dormancy
        if days_since_login >= thresholds.dormancy_days_critical:
            score = max(score, 0.6)
            details_parts.append(
                f"Activity after {days_since_login} days of dormancy"
            )
        elif days_since_login >= thresholds.dormancy_days_warning:
            score = max(score, 0.3)
            details_parts.append(
                f"Activity after {days_since_login} days of inactivity"
            )

        # Using features never used before
        if profile and profile.engagement_baseline.typical_features_used:
            new_features = [
                a for a in actions
                if a not in profile.engagement_baseline.typical_features_used
            ]
            if new_features:
                novelty_ratio = len(new_features) / max(len(actions), 1)
                if novelty_ratio > 0.5:
                    score = max(score, 0.4)
                    details_parts.append(
                        f"Using {len(new_features)} unfamiliar features"
                    )

        if not details_parts:
            details_parts.append("Normal engagement pattern")

        return DimensionAnomalyScore(
            dimension="engagement", score=_clamp(score), details="; ".join(details_parts)
        )

    def _classify(
        self, composite: float, thresholds: Any
    ) -> AnomalyClassification:
        """Classify composite score into risk categories."""
        if composite >= thresholds.high_risk_max:
            return AnomalyClassification.CRITICAL
        elif composite >= thresholds.suspicious_max:
            return AnomalyClassification.HIGH_RISK
        elif composite >= thresholds.normal_max:
            return AnomalyClassification.SUSPICIOUS
        else:
            return AnomalyClassification.NORMAL

    def _recommend_action(
        self, classification: AnomalyClassification
    ) -> RecommendedAction:
        """Map classification to recommended action."""
        mapping = {
            AnomalyClassification.NORMAL: RecommendedAction.NONE,
            AnomalyClassification.SUSPICIOUS: RecommendedAction.MONITOR,
            AnomalyClassification.HIGH_RISK: RecommendedAction.CHALLENGE,
            AnomalyClassification.CRITICAL: RecommendedAction.TERMINATE,
        }
        return mapping[classification]
