"""CTR (Currency Transaction Report) threshold tracking and auto-flagging (Task 8.2).

Maintains per-user, per-business-day running totals of all cash-equivalent
transactions and generates CTR obligations when the $10,000 threshold is met.

Regulatory basis:
  31 CFR § 1010.311 — Filing obligations for CTRs
  31 CFR § 1010.313 — Aggregation of multiple currency transactions
  31 CFR § 1010.306(a)(1) — CTR must be filed within 15 calendar days

Key design decisions:
  - "Cash equivalent" for Trebanx: circle contributions, circle payouts,
    remittance sends, remittance receives.
  - Business day boundary: defined in the user's local timezone.
  - Running totals are persisted and survive service restarts.
  - CTR alerts are non-dismissable without documented rationale.
"""

import uuid
from datetime import UTC, datetime, timedelta, timezone

import structlog

from .config import ComplianceConfig, default_config
from .models import (
    AlertPriority,
    AlertStatus,
    AlertType,
    ComplianceAlert,
    ComplianceTransaction,
    CTRDailyTotal,
    CTRFilingPackage,
    RecommendedAction,
)
from .monitoring import check_ctr_threshold

logger = structlog.get_logger()


def _get_business_date(
    dt: datetime, tz_offset_hours: float = -5.0
) -> str:
    """Determine the business date for a transaction timestamp.

    Args:
        dt: Transaction timestamp (should be timezone-aware).
        tz_offset_hours: Offset from UTC for the user's local timezone.
            Default -5.0 = US Eastern Standard Time (most Trebanx users).

    Returns:
        Business date as YYYY-MM-DD string in the user's local timezone.
    """
    tz = timezone(timedelta(hours=tz_offset_hours))
    local_dt = dt.astimezone(tz)
    return local_dt.strftime("%Y-%m-%d")


class CTRTracker:
    """Per-user daily cumulative CTR tracking.

    In production, running totals are persisted in PostgreSQL. This class
    provides the in-memory logic with a dict-based store that can be
    replaced with a database-backed implementation.
    """

    def __init__(self, config: ComplianceConfig | None = None) -> None:
        self.config = config or default_config
        # In-memory store: {(user_id, business_date): CTRDailyTotal}
        self._daily_totals: dict[tuple[str, str], CTRDailyTotal] = {}
        # Filing packages: {package_id: CTRFilingPackage}
        self._filing_packages: dict[str, CTRFilingPackage] = {}
        # Alerts: {alert_id: ComplianceAlert}
        self._alerts: dict[str, ComplianceAlert] = {}

    def get_daily_total(
        self, user_id: str, business_date: str | None = None
    ) -> CTRDailyTotal:
        """Get the current business day cumulative total for a user.

        If no business_date is provided, uses the current date (UTC-5).
        """
        if business_date is None:
            business_date = _get_business_date(datetime.now(UTC))

        key = (user_id, business_date)
        if key not in self._daily_totals:
            self._daily_totals[key] = CTRDailyTotal(
                user_id=user_id,
                business_date=business_date,
            )
        return self._daily_totals[key]

    def process_transaction(
        self,
        transaction: ComplianceTransaction,
        tz_offset_hours: float = -5.0,
    ) -> list[ComplianceAlert]:
        """Process a single transaction for CTR tracking.

        Updates the daily cumulative total and generates alerts if thresholds
        are met. Returns a list of generated alerts.
        """
        # Only track cash-equivalent transaction types
        if (
            transaction.transaction_type
            and transaction.transaction_type not in self.config.ctr.cash_equivalent_types
        ):
            return []

        business_date = _get_business_date(transaction.initiated_at, tz_offset_hours)
        daily = self.get_daily_total(transaction.user_id, business_date)

        # Add transaction to running total
        daily.cumulative_amount += transaction.amount
        daily.transaction_ids.append(transaction.transaction_id)
        daily.transaction_details.append(
            {
                "transaction_id": transaction.transaction_id,
                "amount": transaction.amount,
                "type": transaction.transaction_type,
                "timestamp": transaction.initiated_at.isoformat(),
            }
        )

        alerts: list[ComplianceAlert] = []

        # Check if CTR threshold is now met
        if daily.cumulative_amount >= self.config.ctr.ctr_threshold:
            if not daily.threshold_met:
                daily.threshold_met = True

                # Generate CTR alert
                ctr_alerts = check_ctr_threshold(
                    user_id=transaction.user_id,
                    daily_total=daily.cumulative_amount,
                    transaction_ids=daily.transaction_ids,
                    config=self.config,
                )
                for alert in ctr_alerts:
                    if alert.recommended_action == RecommendedAction.FILE_CTR:
                        self._alerts[alert.alert_id] = alert
                        daily.alert_generated = True
                        alerts.append(alert)

                        # Auto-assemble filing package
                        package = self._assemble_filing_package(
                            user_id=transaction.user_id,
                            business_date=business_date,
                            daily=daily,
                        )
                        self._filing_packages[package.package_id] = package

                        logger.warning(
                            "ctr_obligation_triggered",
                            user_id=transaction.user_id,
                            business_date=business_date,
                            cumulative_amount=daily.cumulative_amount,
                            transaction_count=len(daily.transaction_ids),
                            package_id=package.package_id,
                        )
        else:
            # Check pre-threshold warnings
            for warning_level in sorted(
                self.config.ctr.pre_threshold_warnings, reverse=True
            ):
                if daily.cumulative_amount >= warning_level:
                    warning_alerts = check_ctr_threshold(
                        user_id=transaction.user_id,
                        daily_total=daily.cumulative_amount,
                        transaction_ids=daily.transaction_ids,
                        config=self.config,
                    )
                    for alert in warning_alerts:
                        self._alerts[alert.alert_id] = alert
                        alerts.append(alert)
                    break

        return alerts

    def _assemble_filing_package(
        self,
        user_id: str,
        business_date: str,
        daily: CTRDailyTotal,
    ) -> CTRFilingPackage:
        """Assemble the data needed for a CTR filing.

        This does not file the CTR — it prepares everything so filing is a
        one-click operation for the BSA officer.

        Per 31 CFR § 1010.306(a)(1), the CTR must be filed within 15
        calendar days of the transaction date.
        """
        filing_deadline = datetime.strptime(business_date, "%Y-%m-%d").replace(
            tzinfo=UTC
        ) + timedelta(days=15)

        return CTRFilingPackage(
            package_id=str(uuid.uuid4()),
            user_id=user_id,
            business_date=business_date,
            total_amount=daily.cumulative_amount,
            transaction_count=len(daily.transaction_ids),
            transaction_details=daily.transaction_details,
            customer_info={
                "user_id": user_id,
                "note": "Customer identification details to be populated from KYC records",
            },
            filing_metadata={
                "filing_deadline": filing_deadline.isoformat(),
                "regulatory_basis": "31 CFR § 1010.311",
                "aggregation_basis": "31 CFR § 1010.313",
                "threshold_amount": self.config.ctr.ctr_threshold,
                "auto_assembled": True,
            },
            status="pending",
            assembled_at=datetime.now(UTC),
        )

    def get_pending_obligations(self) -> list[CTRFilingPackage]:
        """Get all filing packages with pending CTR obligations."""
        return [
            pkg
            for pkg in self._filing_packages.values()
            if pkg.status == "pending"
        ]

    def get_filing_history(self) -> list[CTRFilingPackage]:
        """Get all CTR filing packages."""
        return list(self._filing_packages.values())

    def mark_filed(self, package_id: str, filing_reference: str) -> CTRFilingPackage | None:
        """Mark a CTR filing package as filed."""
        pkg = self._filing_packages.get(package_id)
        if pkg:
            pkg.status = "filed"
            pkg.filed_at = datetime.now(UTC)
            pkg.filing_reference = filing_reference
            logger.info(
                "ctr_filed",
                package_id=package_id,
                filing_reference=filing_reference,
            )
        return pkg

    def get_alerts(self) -> list[ComplianceAlert]:
        """Get all CTR-related alerts."""
        return list(self._alerts.values())
