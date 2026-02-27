"""Per-user behavioral profile engine.

Builds and maintains a behavioral baseline for each user by consuming
session events and Feast features. Profiles adapt via exponential moving
averages and decay toward broader baselines during inactivity.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import UserProfileDB
from src.features.store import FeatureStore

from .config import BehaviorConfig, default_config
from .models import (
    DeviceBaseline,
    EngagementBaseline,
    GeographicBaseline,
    ProfileStatus,
    SessionBaseline,
    TemporalBaseline,
    UserBehaviorProfile,
)

logger = structlog.get_logger()


class BehaviorProfileEngine:
    """Builds, updates, and retrieves per-user behavioral profiles."""

    def __init__(
        self,
        config: BehaviorConfig | None = None,
        feature_store: FeatureStore | None = None,
    ) -> None:
        self._config = config or default_config
        self._feature_store = feature_store or FeatureStore()

    async def build_profile(
        self,
        user_id: str,
        session: AsyncSession,
        historical_sessions: list[dict[str, Any]] | None = None,
    ) -> UserBehaviorProfile:
        """Build a behavioral profile from historical session data.

        If historical_sessions is provided, uses them directly.
        Otherwise, fetches features from the feature store.
        """
        cfg = self._config.profile

        # Fetch features from Feast if no historical sessions provided
        if historical_sessions is None:
            features = await self._feature_store.get_features(user_id, "behavior")
            historical_sessions = features.get("sessions", [])

        now = datetime.now(UTC)
        session_count = len(historical_sessions)

        # Build baselines from historical data
        session_baseline = self._build_session_baseline(historical_sessions)
        temporal_baseline = self._build_temporal_baseline(historical_sessions)
        device_baseline = self._build_device_baseline(historical_sessions)
        geographic_baseline = self._build_geographic_baseline(historical_sessions)
        engagement_baseline = self._build_engagement_baseline(historical_sessions)

        # Determine profile status
        distinct_days = self._count_distinct_days(historical_sessions)
        if session_count >= cfg.min_sessions_active and distinct_days >= cfg.min_days_active:
            status = ProfileStatus.ACTIVE
        else:
            status = ProfileStatus.BUILDING

        profile = UserBehaviorProfile(
            user_id=user_id,
            profile_status=status,
            profile_maturity=session_count,
            session_baseline=session_baseline,
            temporal_baseline=temporal_baseline,
            device_baseline=device_baseline,
            geographic_baseline=geographic_baseline,
            engagement_baseline=engagement_baseline,
            last_updated=now,
        )

        # Persist to database
        await self._persist_profile(profile, session)

        logger.info(
            "profile_built",
            user_id=user_id,
            status=status.value,
            maturity=session_count,
            distinct_days=distinct_days,
        )

        return profile

    async def update_profile(
        self,
        user_id: str,
        session_event: dict[str, Any],
        db_session: AsyncSession,
    ) -> UserBehaviorProfile:
        """Incrementally update a profile with a new session event.

        Uses exponential moving averages so the profile adapts to gradual
        behavior changes without triggering permanent alerts.
        """
        cfg = self._config.profile
        alpha = cfg.ema_decay_rate

        # Get existing profile
        profile = await self.get_profile(user_id, db_session)
        if profile is None:
            # First session — build a fresh profile
            return await self.build_profile(
                user_id, db_session, historical_sessions=[session_event]
            )

        now = datetime.now(UTC)

        # Check staleness and reset tolerance if needed
        days_inactive = (now - profile.last_updated).days
        if days_inactive >= cfg.staleness_threshold_days:
            profile.profile_status = ProfileStatus.STALE
            # Use a lower alpha for stale profiles (slower adaptation back)
            alpha = alpha * 0.5

        # Increment maturity
        profile.profile_maturity += 1

        # Update session baseline with EMA
        duration = session_event.get("session_duration_seconds", 0.0)
        actions = session_event.get("action_count", 0)
        sb = profile.session_baseline
        sb.avg_duration = self._ema(sb.avg_duration, duration, alpha)
        sb.std_duration = self._ema_std(sb.std_duration, sb.avg_duration, duration, alpha)
        sb.avg_actions = self._ema(sb.avg_actions, float(actions), alpha)
        sb.std_actions = self._ema_std(sb.std_actions, sb.avg_actions, float(actions), alpha)

        # Update action sequences
        action_list = session_event.get("actions", [])
        if action_list:
            self._update_action_sequences(sb, action_list)

        # Update temporal baseline
        session_start = session_event.get("session_start")
        if session_start:
            if isinstance(session_start, str):
                session_start = datetime.fromisoformat(session_start)
            self._update_temporal_baseline(profile.temporal_baseline, session_start, alpha)

        # Update device baseline
        device_id = session_event.get("device_id")
        device_type = session_event.get("device_type")
        if device_id:
            self._update_device_baseline(profile.device_baseline, device_id, device_type, cfg)

        # Update geographic baseline
        geo = session_event.get("geo_location")
        if geo:
            self._update_geographic_baseline(profile.geographic_baseline, geo, cfg)

        # Update engagement baseline
        features_used = session_event.get("features_used", [])
        if features_used:
            eb = profile.engagement_baseline
            for feature in features_used:
                if feature not in eb.typical_features_used:
                    eb.typical_features_used.append(feature)

        # Re-evaluate profile status
        if profile.profile_maturity >= cfg.min_sessions_active:
            if profile.profile_status == ProfileStatus.STALE and days_inactive < cfg.staleness_threshold_days:
                profile.profile_status = ProfileStatus.ACTIVE
            elif profile.profile_status == ProfileStatus.BUILDING:
                profile.profile_status = ProfileStatus.ACTIVE

        # If we were stale and just got a new session, start re-establishing
        if profile.profile_status == ProfileStatus.STALE:
            # Keep stale until enough new sessions re-establish the baseline
            pass

        profile.last_updated = now

        # Persist
        await self._persist_profile(profile, db_session)

        logger.info(
            "profile_updated",
            user_id=user_id,
            status=profile.profile_status.value,
            maturity=profile.profile_maturity,
        )

        return profile

    async def get_profile(
        self,
        user_id: str,
        db_session: AsyncSession,
    ) -> UserBehaviorProfile | None:
        """Retrieve the current profile from PostgreSQL."""
        stmt = select(UserProfileDB).where(UserProfileDB.user_id == user_id)
        result = await db_session.execute(stmt)
        row = result.scalar_one_or_none()

        if row is None:
            return None

        features = row.behavioral_features or {}
        now = datetime.now(UTC)

        profile = UserBehaviorProfile(
            user_id=row.user_id,
            profile_status=ProfileStatus(features.get("profile_status", "building")),
            profile_maturity=features.get("profile_maturity", 0),
            session_baseline=SessionBaseline(**features.get("session_baseline", {})),
            temporal_baseline=TemporalBaseline(**features.get("temporal_baseline", {})),
            device_baseline=DeviceBaseline(**features.get("device_baseline", {})),
            geographic_baseline=GeographicBaseline(**features.get("geographic_baseline", {})),
            engagement_baseline=EngagementBaseline(**features.get("engagement_baseline", {})),
            last_updated=row.last_updated,
            profile_version=features.get("profile_version", "behavior-profile-v1"),
        )

        # Apply staleness check
        days_inactive = (now - profile.last_updated).days
        if (
            days_inactive >= self._config.profile.staleness_threshold_days
            and profile.profile_status == ProfileStatus.ACTIVE
        ):
            profile.profile_status = ProfileStatus.STALE

        return profile

    async def _persist_profile(
        self,
        profile: UserBehaviorProfile,
        db_session: AsyncSession,
    ) -> None:
        """Persist profile to PostgreSQL."""
        features = {
            "profile_status": profile.profile_status.value,
            "profile_maturity": profile.profile_maturity,
            "session_baseline": profile.session_baseline.model_dump(),
            "temporal_baseline": profile.temporal_baseline.model_dump(),
            "device_baseline": profile.device_baseline.model_dump(),
            "geographic_baseline": profile.geographic_baseline.model_dump(),
            "engagement_baseline": profile.engagement_baseline.model_dump(),
            "profile_version": profile.profile_version,
        }

        stmt = select(UserProfileDB).where(UserProfileDB.user_id == profile.user_id)
        result = await db_session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.behavioral_features = features
            existing.risk_level = self._compute_risk_level(profile)
            existing.last_updated = profile.last_updated
        else:
            row = UserProfileDB(
                user_id=profile.user_id,
                behavioral_features=features,
                risk_level=self._compute_risk_level(profile),
                last_updated=profile.last_updated,
            )
            db_session.add(row)

        await db_session.commit()

    def _compute_risk_level(self, profile: UserBehaviorProfile) -> str:
        """Compute a simple risk level from profile status."""
        if profile.profile_status == ProfileStatus.STALE:
            return "medium"
        if profile.profile_status == ProfileStatus.BUILDING:
            return "low"
        return "low"

    # --- Baseline Building Helpers ---

    def _build_session_baseline(self, sessions: list[dict]) -> SessionBaseline:
        if not sessions:
            return SessionBaseline()

        durations = [s.get("session_duration_seconds", 0.0) for s in sessions]
        actions = [float(s.get("action_count", 0)) for s in sessions]

        avg_dur = sum(durations) / len(durations) if durations else 0.0
        std_dur = self._compute_std(durations) if len(durations) > 1 else 0.0
        avg_act = sum(actions) / len(actions) if actions else 0.0
        std_act = self._compute_std(actions) if len(actions) > 1 else 0.0

        # Extract top action sequences
        sequences = []
        for s in sessions:
            action_list = s.get("actions", [])
            if action_list:
                sequences.append(action_list[:10])  # truncate long sequences
        top_sequences = self._get_top_sequences(sequences, max_count=5)

        return SessionBaseline(
            avg_duration=avg_dur,
            std_duration=std_dur,
            avg_actions=avg_act,
            std_actions=std_act,
            typical_action_sequences=top_sequences,
        )

    def _build_temporal_baseline(self, sessions: list[dict]) -> TemporalBaseline:
        if not sessions:
            return TemporalBaseline()

        hours: dict[int, float] = {}
        days: dict[int, float] = {}

        for s in sessions:
            start = s.get("session_start")
            if start:
                if isinstance(start, str):
                    start = datetime.fromisoformat(start)
                h = start.hour
                d = start.weekday()
                hours[h] = hours.get(h, 0) + 1
                days[d] = days.get(d, 0) + 1

        # Normalize to frequencies
        total_sessions = len(sessions)
        if total_sessions > 0:
            hours = {k: v / total_sessions for k, v in hours.items()}
            days = {k: v / total_sessions for k, v in days.items()}

        # Compute sessions per week
        if len(sessions) >= 2:
            dates = []
            for s in sessions:
                start = s.get("session_start")
                if start:
                    if isinstance(start, str):
                        start = datetime.fromisoformat(start)
                    dates.append(start)
            if len(dates) >= 2:
                dates.sort()
                span_weeks = max((dates[-1] - dates[0]).days / 7.0, 1.0)
                freq_mean = len(dates) / span_weeks
                freq_std = 0.0  # simplified
            else:
                freq_mean = 0.0
                freq_std = 0.0
        else:
            freq_mean = 0.0
            freq_std = 0.0

        return TemporalBaseline(
            typical_hours=hours,
            typical_days=days,
            typical_frequency_mean=freq_mean,
            typical_frequency_std=freq_std,
        )

    def _build_device_baseline(self, sessions: list[dict]) -> DeviceBaseline:
        if not sessions:
            return DeviceBaseline()

        device_counts: dict[str, int] = {}
        platforms: set[str] = set()

        for s in sessions:
            device_id = s.get("device_id")
            if device_id:
                device_counts[device_id] = device_counts.get(device_id, 0) + 1
            device_type = s.get("device_type")
            if device_type:
                platforms.add(device_type.lower())

        known_devices = list(device_counts.keys())
        primary_device = max(device_counts, key=device_counts.get) if device_counts else None

        # Device switch rate: fraction of sessions where device != previous session's device
        switch_count = 0
        prev_device = None
        for s in sessions:
            device_id = s.get("device_id")
            if device_id and prev_device and device_id != prev_device:
                switch_count += 1
            prev_device = device_id
        switch_rate = switch_count / max(len(sessions) - 1, 1) if len(sessions) > 1 else 0.0

        return DeviceBaseline(
            known_devices=known_devices[:self._config.profile.max_known_devices],
            primary_device=primary_device,
            device_switch_rate=switch_rate,
            device_platforms=sorted(platforms),
        )

    def _build_geographic_baseline(self, sessions: list[dict]) -> GeographicBaseline:
        if not sessions:
            return GeographicBaseline()

        location_counts: dict[str, int] = {}
        locations_list: list[dict[str, str]] = []
        travel_patterns: list[dict[str, str]] = []
        prev_location = None

        for s in sessions:
            geo = s.get("geo_location")
            if geo:
                city = geo.get("city", "unknown")
                country = geo.get("country", "unknown")
                loc_key = f"{city}:{country}"
                location_counts[loc_key] = location_counts.get(loc_key, 0) + 1

                loc_dict = {"city": city, "country": country}
                if loc_dict not in locations_list:
                    locations_list.append(loc_dict)

                # Track travel patterns
                if prev_location and prev_location != loc_key:
                    pattern = {"from": prev_location, "to": loc_key}
                    if pattern not in travel_patterns:
                        travel_patterns.append(pattern)
                prev_location = loc_key

        primary_loc_key = max(location_counts, key=location_counts.get) if location_counts else None
        primary_location = None
        if primary_loc_key:
            parts = primary_loc_key.split(":")
            primary_location = {"city": parts[0], "country": parts[1]}

        return GeographicBaseline(
            known_locations=locations_list[:self._config.profile.max_known_locations],
            primary_location=primary_location,
            typical_travel_patterns=travel_patterns[:20],
        )

    def _build_engagement_baseline(self, sessions: list[dict]) -> EngagementBaseline:
        if not sessions:
            return EngagementBaseline()

        all_features: set[str] = set()
        for s in sessions:
            features_used = s.get("features_used", [])
            all_features.update(features_used)

        # Sessions per week
        dates = []
        for s in sessions:
            start = s.get("session_start")
            if start:
                if isinstance(start, str):
                    start = datetime.fromisoformat(start)
                dates.append(start)
        if len(dates) >= 2:
            dates.sort()
            span_weeks = max((dates[-1] - dates[0]).days / 7.0, 1.0)
            avg_per_week = len(dates) / span_weeks
        else:
            avg_per_week = 0.0

        return EngagementBaseline(
            typical_features_used=sorted(all_features),
            feature_usage_breadth=min(len(all_features) / 10.0, 1.0),  # normalize to 0-1
            avg_sessions_per_week=avg_per_week,
        )

    # --- Update Helpers ---

    def _update_temporal_baseline(
        self, baseline: TemporalBaseline, session_start: datetime, alpha: float
    ) -> None:
        h = session_start.hour
        d = session_start.weekday()

        # Update hour distribution with EMA
        for hour in baseline.typical_hours:
            if hour == h:
                baseline.typical_hours[hour] = self._ema(baseline.typical_hours[hour], 1.0, alpha)
            else:
                baseline.typical_hours[hour] = self._ema(baseline.typical_hours[hour], 0.0, alpha)
        if h not in baseline.typical_hours:
            baseline.typical_hours[h] = alpha

        # Update day distribution with EMA
        for day in baseline.typical_days:
            if day == d:
                baseline.typical_days[day] = self._ema(baseline.typical_days[day], 1.0, alpha)
            else:
                baseline.typical_days[day] = self._ema(baseline.typical_days[day], 0.0, alpha)
        if d not in baseline.typical_days:
            baseline.typical_days[d] = alpha

    def _update_device_baseline(
        self, baseline: DeviceBaseline, device_id: str, device_type: str | None, cfg: Any
    ) -> None:
        if device_id not in baseline.known_devices:
            baseline.known_devices.append(device_id)
            # Trim if too many
            if len(baseline.known_devices) > cfg.max_known_devices:
                baseline.known_devices = baseline.known_devices[-cfg.max_known_devices :]

        if device_type and device_type.lower() not in baseline.device_platforms:
            baseline.device_platforms.append(device_type.lower())

        # Update primary device (most recent used = likely primary in EMA sense)
        baseline.primary_device = device_id

    def _update_geographic_baseline(
        self, baseline: GeographicBaseline, geo: dict, cfg: Any
    ) -> None:
        city = geo.get("city", "unknown")
        country = geo.get("country", "unknown")
        loc_dict = {"city": city, "country": country}

        if loc_dict not in baseline.known_locations:
            baseline.known_locations.append(loc_dict)
            if len(baseline.known_locations) > cfg.max_known_locations:
                baseline.known_locations = baseline.known_locations[-cfg.max_known_locations :]

        # Track travel pattern from previous primary
        if baseline.primary_location and baseline.primary_location != loc_dict:
            pattern = {
                "from": f"{baseline.primary_location.get('city')}:{baseline.primary_location.get('country')}",
                "to": f"{city}:{country}",
            }
            if pattern not in baseline.typical_travel_patterns:
                baseline.typical_travel_patterns.append(pattern)

        baseline.primary_location = loc_dict

    def _update_action_sequences(self, baseline: SessionBaseline, actions: list[str]) -> None:
        """Track the most common action sequences."""
        seq = actions[:10]
        if seq not in baseline.typical_action_sequences:
            baseline.typical_action_sequences.append(seq)
            if len(baseline.typical_action_sequences) > 10:
                baseline.typical_action_sequences = baseline.typical_action_sequences[-10:]

    # --- Math Helpers ---

    @staticmethod
    def _ema(current: float, new_value: float, alpha: float) -> float:
        """Exponential moving average update."""
        return alpha * new_value + (1 - alpha) * current

    @staticmethod
    def _ema_std(
        current_std: float, current_mean: float, new_value: float, alpha: float
    ) -> float:
        """Update standard deviation estimate with EMA."""
        deviation = abs(new_value - current_mean)
        return alpha * deviation + (1 - alpha) * current_std

    @staticmethod
    def _compute_std(values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
        return variance**0.5

    @staticmethod
    def _count_distinct_days(sessions: list[dict]) -> int:
        """Count distinct dates across sessions."""
        dates: set[str] = set()
        for s in sessions:
            start = s.get("session_start")
            if start:
                if isinstance(start, str):
                    start = datetime.fromisoformat(start)
                dates.add(start.strftime("%Y-%m-%d"))
        return len(dates)

    @staticmethod
    def _get_top_sequences(sequences: list[list[str]], max_count: int = 5) -> list[list[str]]:
        """Return the most common action sequences."""
        if not sequences:
            return []
        # Count occurrences by tuple (hashable)
        counts: dict[tuple, int] = {}
        for seq in sequences:
            key = tuple(seq)
            counts[key] = counts.get(key, 0) + 1
        sorted_seqs = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        return [list(k) for k, _ in sorted_seqs[:max_count]]
