"""Compute transaction features from historical raw_events data."""

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import Float, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import RawEvent

from .models import TransactionFeatures

logger = structlog.get_logger()


class FeatureComputer:
    """Queries raw_events to compute TransactionFeatures for a user/transaction."""

    async def compute(
        self,
        session: AsyncSession,
        user_id: str,
        device_id: str | None = None,
        geo_location: dict | None = None,
        now: datetime | None = None,
    ) -> TransactionFeatures:
        now = now or datetime.now(UTC)
        one_hour_ago = now - timedelta(hours=1)
        one_day_ago = now - timedelta(hours=24)
        seven_days_ago = now - timedelta(days=7)
        thirty_days_ago = now - timedelta(days=30)

        # All queries filter on transaction events for this user
        base_filter = (
            RawEvent.event_type == "transaction-initiated",
            RawEvent.payload["payload"]["user_id"].astext == user_id,
        )

        # Velocity: count and sum in 1h/24h windows
        velocity_1h = await self._velocity(session, base_filter, one_hour_ago, now)
        velocity_24h = await self._velocity(session, base_filter, one_day_ago, now)

        # Device uniqueness over 7d
        unique_devices_7d = 0
        is_new_device = False
        if device_id:
            unique_devices_7d = await self._unique_device_count(
                session, base_filter, seven_days_ago, now
            )
            is_new_device = await self._is_first_occurrence_device(session, base_filter, device_id)

        # Geo uniqueness over 7d
        unique_countries_7d = 0
        is_new_country = False
        if geo_location and geo_location.get("country"):
            unique_countries_7d = await self._unique_country_count(
                session, base_filter, seven_days_ago, now
            )
            is_new_country = await self._is_first_occurrence_country(
                session, base_filter, geo_location["country"]
            )

        # Last transaction geo and time
        last_txn = await self._last_transaction(session, base_filter, now)
        time_since_last: float | None = None
        last_geo: dict | None = None

        if last_txn:
            last_timestamp = last_txn.get("timestamp")
            if last_timestamp:
                time_since_last = (now - last_timestamp).total_seconds()

            prev_geo = last_txn.get("geo_location")
            if prev_geo and geo_location:
                last_geo = {
                    "current_lat": geo_location.get("latitude"),
                    "current_lon": geo_location.get("longitude"),
                    "prev_lat": prev_geo.get("latitude"),
                    "prev_lon": prev_geo.get("longitude"),
                }

        # Amount statistics over 30d
        avg_amount, stddev_amount = await self._amount_stats(
            session, base_filter, thirty_days_ago, now
        )

        return TransactionFeatures(
            velocity_count_1h=velocity_1h["count"],
            velocity_count_24h=velocity_24h["count"],
            velocity_amount_1h=velocity_1h["sum"],
            velocity_amount_24h=velocity_24h["sum"],
            unique_devices_7d=unique_devices_7d,
            unique_countries_7d=unique_countries_7d,
            is_new_device=is_new_device,
            is_new_country=is_new_country,
            last_geo_location=last_geo,
            time_since_last_txn_seconds=time_since_last,
            avg_amount_30d=avg_amount,
            stddev_amount_30d=stddev_amount,
        )

    async def _velocity(
        self,
        session: AsyncSession,
        base_filter: tuple,
        start: datetime,
        end: datetime,
    ) -> dict:
        stmt = select(
            func.count().label("cnt"),
            func.coalesce(
                func.sum(RawEvent.payload["payload"]["amount"].astext.cast(Float)),
                0,
            ).label("total"),
        ).where(
            *base_filter,
            RawEvent.received_at >= start,
            RawEvent.received_at < end,
        )
        result = await session.execute(stmt)
        row = result.one()
        return {"count": row.cnt, "sum": float(row.total)}

    async def _unique_device_count(
        self,
        session: AsyncSession,
        base_filter: tuple,
        start: datetime,
        end: datetime,
    ) -> int:
        stmt = select(
            func.count(func.distinct(RawEvent.payload["payload"]["device_id"].astext))
        ).where(
            *base_filter,
            RawEvent.received_at >= start,
            RawEvent.received_at < end,
            RawEvent.payload["payload"]["device_id"].astext.isnot(None),
        )
        result = await session.execute(stmt)
        return result.scalar_one()

    async def _is_first_occurrence_device(
        self,
        session: AsyncSession,
        base_filter: tuple,
        device_id: str,
    ) -> bool:
        stmt = select(func.count()).where(
            *base_filter,
            RawEvent.payload["payload"]["device_id"].astext == device_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one() == 0

    async def _unique_country_count(
        self,
        session: AsyncSession,
        base_filter: tuple,
        start: datetime,
        end: datetime,
    ) -> int:
        stmt = select(
            func.count(func.distinct(RawEvent.payload["payload"]["geo_location"]["country"].astext))
        ).where(
            *base_filter,
            RawEvent.received_at >= start,
            RawEvent.received_at < end,
        )
        result = await session.execute(stmt)
        return result.scalar_one()

    async def _is_first_occurrence_country(
        self,
        session: AsyncSession,
        base_filter: tuple,
        country: str,
    ) -> bool:
        stmt = select(func.count()).where(
            *base_filter,
            RawEvent.payload["payload"]["geo_location"]["country"].astext == country,
        )
        result = await session.execute(stmt)
        return result.scalar_one() == 0

    async def _last_transaction(
        self,
        session: AsyncSession,
        base_filter: tuple,
        before: datetime,
    ) -> dict | None:
        stmt = (
            select(RawEvent.payload, RawEvent.received_at)
            .where(
                *base_filter,
                RawEvent.received_at < before,
            )
            .order_by(RawEvent.received_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        row = result.first()
        if not row:
            return None

        payload = row[0].get("payload", {})
        geo = payload.get("geo_location")
        return {
            "timestamp": row[1],
            "geo_location": geo,
        }

    async def _amount_stats(
        self,
        session: AsyncSession,
        base_filter: tuple,
        start: datetime,
        end: datetime,
    ) -> tuple[float, float]:
        amount_expr = RawEvent.payload["payload"]["amount"].astext.cast(Float)
        stmt = select(
            func.coalesce(func.avg(amount_expr), 0).label("avg"),
            func.coalesce(func.stddev(amount_expr), 0).label("stddev"),
        ).where(
            *base_filter,
            RawEvent.received_at >= start,
            RawEvent.received_at < end,
        )
        result = await session.execute(stmt)
        row = result.one()
        return float(row.avg), float(row.stddev)
