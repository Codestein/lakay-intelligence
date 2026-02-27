"""BSA/AML transaction monitoring rules (Task 8.1).

Implements six core monitoring rules for Trebanx compliance:

  M-1  CTR threshold monitoring       (31 CFR § 1010.311)
  M-2  Suspicious round-amount        (31 USC § 5324; FinCEN Advisory FIN-2014-A007)
  M-3  Rapid movement / layering      (31 CFR § 1022.320)
  M-4  Unusual transaction volume     (31 CFR § 1022.210(d))
  M-5  Geographic risk indicators     (FATF Rec. 19; 31 CFR § 1022.210(d)(4))
  M-6  Circle-based compliance        (31 CFR § 1010.311 aggregation)

Each rule accepts a transaction (or batch) and a feature context, and returns
a list of ComplianceAlert objects when conditions are met.
"""

import uuid
from datetime import UTC, datetime, timedelta

import structlog

from .config import ComplianceConfig, default_config
from .models import (
    AlertPriority,
    AlertStatus,
    AlertType,
    ComplianceAlert,
    ComplianceTransaction,
    RecommendedAction,
)

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Rule M-1: CTR Threshold Monitoring
# ---------------------------------------------------------------------------


def check_ctr_threshold(
    user_id: str,
    daily_total: float,
    transaction_ids: list[str],
    config: ComplianceConfig = default_config,
) -> list[ComplianceAlert]:
    """Check if a user's daily cumulative total triggers CTR obligations.

    Regulatory basis: 31 CFR § 1010.311 — CTR required for cash transactions
    (or aggregated transactions) exceeding $10,000 per business day.

    Also generates pre-threshold warnings per FinCEN guidance on CTR
    aggregation monitoring.
    """
    if not config.ctr.enabled:
        return []

    alerts: list[ComplianceAlert] = []
    now = datetime.now(UTC)

    # Full CTR threshold met
    if daily_total >= config.ctr.ctr_threshold:
        priority = AlertPriority(config.ctr.priority_override) if config.ctr.priority_override else AlertPriority.URGENT
        alerts.append(
            ComplianceAlert(
                alert_id=str(uuid.uuid4()),
                alert_type=AlertType.CTR_THRESHOLD,
                user_id=user_id,
                transaction_ids=transaction_ids,
                amount_total=daily_total,
                description=(
                    f"Daily cumulative cash transactions for user {user_id} "
                    f"total ${daily_total:,.2f}, exceeding the $10,000 CTR "
                    f"reporting threshold (31 CFR § 1010.311). "
                    f"{len(transaction_ids)} transaction(s) contribute to this total."
                ),
                regulatory_basis=(
                    "31 CFR § 1010.311 — Currency transaction reports. "
                    "31 CFR § 1010.313 — Aggregation of currency transactions."
                ),
                recommended_action=RecommendedAction.FILE_CTR,
                priority=priority,
                status=AlertStatus.NEW,
                created_at=now,
            )
        )
        logger.warning(
            "ctr_threshold_met",
            user_id=user_id,
            daily_total=daily_total,
            transaction_count=len(transaction_ids),
        )
        return alerts

    # Pre-threshold warnings
    for warning_level in sorted(config.ctr.pre_threshold_warnings, reverse=True):
        if daily_total >= warning_level:
            alerts.append(
                ComplianceAlert(
                    alert_id=str(uuid.uuid4()),
                    alert_type=AlertType.CTR_THRESHOLD,
                    user_id=user_id,
                    transaction_ids=transaction_ids,
                    amount_total=daily_total,
                    description=(
                        f"Daily cumulative cash transactions for user {user_id} "
                        f"total ${daily_total:,.2f}, reaching the "
                        f"${warning_level:,.0f} pre-threshold warning level. "
                        f"CTR filing may be required if additional transactions "
                        f"bring the total above $10,000."
                    ),
                    regulatory_basis=(
                        "Pre-threshold warning per FinCEN guidance on CTR "
                        f"aggregation monitoring ({warning_level/config.ctr.ctr_threshold:.0%} "
                        f"of the $10,000 reporting threshold)."
                    ),
                    recommended_action=RecommendedAction.ENHANCED_MONITORING,
                    priority=AlertPriority.ELEVATED,
                    status=AlertStatus.NEW,
                    created_at=now,
                )
            )
            break  # Only the highest applicable warning

    return alerts


# ---------------------------------------------------------------------------
# Rule M-2: Suspicious Round-Amount Patterns
# ---------------------------------------------------------------------------


def check_round_amount(
    transaction: ComplianceTransaction,
    round_amount_ratio_30d: float | None = None,
    config: ComplianceConfig = default_config,
) -> list[ComplianceAlert]:
    """Flag transactions at or just below common thresholds.

    Regulatory basis: FinCEN Advisory FIN-2014-A007 — Transactions at amounts
    designed to evade reporting thresholds. 31 USC § 5324.
    """
    if not config.round_amount.enabled:
        return []

    alerts: list[ComplianceAlert] = []
    now = datetime.now(UTC)

    # Check if amount is suspiciously close to known thresholds
    for threshold in config.round_amount.suspicious_amounts:
        lower = threshold - config.round_amount.tolerance
        if lower <= transaction.amount <= threshold:
            priority = AlertPriority(config.round_amount.priority_override) if config.round_amount.priority_override else AlertPriority.ELEVATED
            alerts.append(
                ComplianceAlert(
                    alert_id=str(uuid.uuid4()),
                    alert_type=AlertType.SUSPICIOUS_ACTIVITY,
                    user_id=transaction.user_id,
                    transaction_ids=[transaction.transaction_id],
                    amount_total=transaction.amount,
                    description=(
                        f"Transaction of ${transaction.amount:,.2f} is at or just "
                        f"below the ${threshold:,.0f} threshold "
                        f"(tolerance: ${config.round_amount.tolerance:,.0f}). "
                        f"This may indicate structuring to evade reporting requirements."
                    ),
                    regulatory_basis=(
                        "31 USC § 5324 — Structuring transactions to evade "
                        "reporting requirements. FinCEN Advisory FIN-2014-A007."
                    ),
                    recommended_action=RecommendedAction.ENHANCED_MONITORING,
                    priority=priority,
                    status=AlertStatus.NEW,
                    created_at=now,
                )
            )
            break

    # Check round-amount ratio from Feast features
    if (
        round_amount_ratio_30d is not None
        and round_amount_ratio_30d >= config.round_amount.round_amount_ratio_threshold
    ):
        alerts.append(
            ComplianceAlert(
                alert_id=str(uuid.uuid4()),
                alert_type=AlertType.SUSPICIOUS_ACTIVITY,
                user_id=transaction.user_id,
                transaction_ids=[transaction.transaction_id],
                amount_total=transaction.amount,
                description=(
                    f"User {transaction.user_id} has a round-amount transaction "
                    f"ratio of {round_amount_ratio_30d:.0%} over the past 30 days, "
                    f"exceeding the {config.round_amount.round_amount_ratio_threshold:.0%} "
                    f"threshold. Statistically unusual proportion of round-amount "
                    f"transactions may indicate structuring."
                ),
                regulatory_basis=(
                    "31 USC § 5324 — Structuring transactions. Pattern-based "
                    "detection per FinCEN Advisory FIN-2014-A007."
                ),
                recommended_action=RecommendedAction.ENHANCED_MONITORING,
                priority=AlertPriority.ELEVATED,
                status=AlertStatus.NEW,
                created_at=now,
            )
        )

    return alerts


# ---------------------------------------------------------------------------
# Rule M-3: Rapid Movement Patterns (Layering)
# ---------------------------------------------------------------------------


def check_rapid_movement(
    user_id: str,
    received_transactions: list[ComplianceTransaction],
    sent_transactions: list[ComplianceTransaction],
    config: ComplianceConfig = default_config,
) -> list[ComplianceAlert]:
    """Detect pass-through behavior (receive-then-send within time window).

    Regulatory basis: 31 CFR § 1022.320(a)(2) — Transactions involving funds
    derived from illegal activity or designed to facilitate criminal activity.
    Rapid movement is a classic layering typology.
    """
    if not config.rapid_movement.enabled:
        return []

    alerts: list[ComplianceAlert] = []
    now = datetime.now(UTC)
    window = timedelta(hours=config.rapid_movement.time_window_hours)

    for received in received_transactions:
        if received.amount < config.rapid_movement.min_amount:
            continue

        min_outbound = received.amount * config.rapid_movement.transfer_ratio_threshold

        for sent in sent_transactions:
            time_diff = sent.initiated_at - received.initiated_at
            if timedelta(0) <= time_diff <= window and sent.amount >= min_outbound:
                priority = AlertPriority(config.rapid_movement.priority_override) if config.rapid_movement.priority_override else AlertPriority.URGENT
                alerts.append(
                    ComplianceAlert(
                        alert_id=str(uuid.uuid4()),
                        alert_type=AlertType.SUSPICIOUS_ACTIVITY,
                        user_id=user_id,
                        transaction_ids=[
                            received.transaction_id,
                            sent.transaction_id,
                        ],
                        amount_total=received.amount + sent.amount,
                        description=(
                            f"User {user_id} received ${received.amount:,.2f} "
                            f"and sent ${sent.amount:,.2f} within "
                            f"{time_diff.total_seconds() / 3600:.1f} hours "
                            f"({sent.amount / received.amount:.0%} of received amount). "
                            f"This rapid movement of funds may indicate layering."
                        ),
                        regulatory_basis=(
                            "31 CFR § 1022.320(a)(2) — Suspicious activity "
                            "reporting for transactions that appear designed to "
                            "facilitate criminal activity. Classic layering typology."
                        ),
                        recommended_action=RecommendedAction.FILE_SAR,
                        priority=priority,
                        status=AlertStatus.NEW,
                        created_at=now,
                    )
                )

    return alerts


# ---------------------------------------------------------------------------
# Rule M-4: Unusual Transaction Volume
# ---------------------------------------------------------------------------


def check_unusual_volume(
    transaction: ComplianceTransaction,
    tx_count_24h: int = 0,
    tx_amount_mean_30d: float = 0.0,
    tx_amount_std_30d: float = 0.0,
    tx_cumulative_7d: float = 0.0,
    config: ComplianceConfig = default_config,
) -> list[ComplianceAlert]:
    """Flag users whose volume significantly exceeds their historical baseline.

    Regulatory basis: 31 CFR § 1022.210(d) — AML program requirement to
    identify and report unusual activity. FinCEN Advisory FIN-2014-A007.
    """
    if not config.unusual_volume.enabled:
        return []

    alerts: list[ComplianceAlert] = []
    now = datetime.now(UTC)

    # Skip if insufficient baseline
    if tx_amount_mean_30d <= 0 or tx_count_24h < config.unusual_volume.min_baseline_transactions:
        return alerts

    # Check multiplier threshold: current transaction vs. 30-day mean
    if transaction.amount >= tx_amount_mean_30d * config.unusual_volume.volume_multiplier_threshold:
        priority = AlertPriority(config.unusual_volume.priority_override) if config.unusual_volume.priority_override else AlertPriority.ELEVATED
        alerts.append(
            ComplianceAlert(
                alert_id=str(uuid.uuid4()),
                alert_type=AlertType.VELOCITY_ANOMALY,
                user_id=transaction.user_id,
                transaction_ids=[transaction.transaction_id],
                amount_total=transaction.amount,
                description=(
                    f"Transaction of ${transaction.amount:,.2f} is "
                    f"{transaction.amount / tx_amount_mean_30d:.1f}x the user's "
                    f"30-day mean of ${tx_amount_mean_30d:,.2f}. This significantly "
                    f"exceeds the {config.unusual_volume.volume_multiplier_threshold}x "
                    f"threshold for unusual volume."
                ),
                regulatory_basis=(
                    "31 CFR § 1022.210(d) — AML program requirement to monitor "
                    "for unusual activity. FinCEN Advisory FIN-2014-A007."
                ),
                recommended_action=RecommendedAction.ENHANCED_MONITORING,
                priority=priority,
                status=AlertStatus.NEW,
                created_at=now,
            )
        )

    # Z-score check
    if tx_amount_std_30d > 0:
        zscore = (transaction.amount - tx_amount_mean_30d) / tx_amount_std_30d
        if zscore >= config.unusual_volume.zscore_threshold:
            alerts.append(
                ComplianceAlert(
                    alert_id=str(uuid.uuid4()),
                    alert_type=AlertType.VELOCITY_ANOMALY,
                    user_id=transaction.user_id,
                    transaction_ids=[transaction.transaction_id],
                    amount_total=transaction.amount,
                    description=(
                        f"Transaction of ${transaction.amount:,.2f} has a z-score "
                        f"of {zscore:.2f} relative to the user's 30-day baseline "
                        f"(mean=${tx_amount_mean_30d:,.2f}, std=${tx_amount_std_30d:,.2f}). "
                        f"This exceeds the {config.unusual_volume.zscore_threshold} "
                        f"standard deviation threshold."
                    ),
                    regulatory_basis=(
                        "31 CFR § 1022.210(d) — Statistical anomaly detection "
                        "for AML monitoring. FinCEN guidance on risk-based approach."
                    ),
                    recommended_action=RecommendedAction.ENHANCED_MONITORING,
                    priority=AlertPriority.ELEVATED,
                    status=AlertStatus.NEW,
                    created_at=now,
                )
            )

    return alerts


# ---------------------------------------------------------------------------
# Rule M-5: Geographic Risk Indicators
# ---------------------------------------------------------------------------


def check_geographic_risk(
    transaction: ComplianceTransaction,
    last_known_country: str | None = None,
    distinct_countries_7d: int = 0,
    config: ComplianceConfig = default_config,
) -> list[ComplianceAlert]:
    """Flag transactions involving high-risk jurisdictions or profile mismatches.

    Regulatory basis: 31 CFR § 1022.210(d)(4) — Enhanced monitoring for
    high-risk jurisdictions. FATF Recommendation 19.
    """
    if not config.geographic.enabled:
        return []

    alerts: list[ComplianceAlert] = []
    now = datetime.now(UTC)

    geo = transaction.geo_country
    if not geo:
        return alerts

    # Check high-risk country
    if geo.upper() in config.geographic.high_risk_countries:
        priority = AlertPriority(config.geographic.priority_override) if config.geographic.priority_override else AlertPriority.CRITICAL
        alerts.append(
            ComplianceAlert(
                alert_id=str(uuid.uuid4()),
                alert_type=AlertType.SUSPICIOUS_ACTIVITY,
                user_id=transaction.user_id,
                transaction_ids=[transaction.transaction_id],
                amount_total=transaction.amount,
                description=(
                    f"Transaction involves high-risk jurisdiction: {geo.upper()}. "
                    f"This country is on the FATF high-risk/increased monitoring list."
                ),
                regulatory_basis=(
                    "31 CFR § 1022.210(d)(4) — Enhanced due diligence for "
                    "high-risk jurisdictions. FATF Recommendation 19 — "
                    "Higher-risk countries and territories."
                ),
                recommended_action=RecommendedAction.ESCALATE_TO_BSA_OFFICER,
                priority=priority,
                status=AlertStatus.NEW,
                created_at=now,
            )
        )

    # Check unexpected origin (profile mismatch)
    if (
        config.geographic.flag_unexpected_origin
        and last_known_country
        and geo.upper() not in config.geographic.expected_corridor_countries
        and geo.upper() != last_known_country.upper()
    ):
        alerts.append(
            ComplianceAlert(
                alert_id=str(uuid.uuid4()),
                alert_type=AlertType.SUSPICIOUS_ACTIVITY,
                user_id=transaction.user_id,
                transaction_ids=[transaction.transaction_id],
                amount_total=transaction.amount,
                description=(
                    f"Transaction initiated from {geo.upper()}, which is outside "
                    f"the expected US-HT corridor and inconsistent with the user's "
                    f"profile (last known country: {last_known_country.upper()}). "
                    f"User has transacted from {distinct_countries_7d} distinct "
                    f"countries in the past 7 days."
                ),
                regulatory_basis=(
                    "31 CFR § 1022.210(d) — AML program requirement to "
                    "monitor for activity inconsistent with customer profile. "
                    "FinCEN guidance on geographic risk factors."
                ),
                recommended_action=RecommendedAction.ENHANCED_MONITORING,
                priority=AlertPriority.ELEVATED,
                status=AlertStatus.NEW,
                created_at=now,
            )
        )

    return alerts


# ---------------------------------------------------------------------------
# Rule M-6: Circle-Based Compliance Concerns
# ---------------------------------------------------------------------------


def check_circle_compliance(
    circle_id: str,
    member_contributions_total: float,
    payout_amount: float | None = None,
    payout_recipient_id: str | None = None,
    payout_recipient_daily_total: float = 0.0,
    members_with_alerts: list[str] | None = None,
    config: ComplianceConfig = default_config,
) -> list[ComplianceAlert]:
    """Flag circle-level compliance concerns.

    Regulatory basis: 31 CFR § 1010.311 — CTR aggregation for circle
    contributions. FinCEN guidance on IVTS monitoring.
    """
    if not config.circle.enabled:
        return []

    alerts: list[ComplianceAlert] = []
    now = datetime.now(UTC)

    # Check aggregate contributions approaching CTR threshold
    warning_amount = config.ctr.ctr_threshold * config.circle.circle_aggregate_warning_pct
    if member_contributions_total >= warning_amount:
        priority = AlertPriority(config.circle.priority_override) if config.circle.priority_override else AlertPriority.ELEVATED
        alerts.append(
            ComplianceAlert(
                alert_id=str(uuid.uuid4()),
                alert_type=AlertType.CTR_THRESHOLD,
                user_id=f"circle:{circle_id}",
                transaction_ids=[],
                amount_total=member_contributions_total,
                description=(
                    f"Circle {circle_id} aggregate member contributions total "
                    f"${member_contributions_total:,.2f}, reaching "
                    f"{member_contributions_total / config.ctr.ctr_threshold:.0%} "
                    f"of the CTR threshold. Enhanced monitoring required."
                ),
                regulatory_basis=(
                    "31 CFR § 1010.311 — Aggregation of currency transactions. "
                    "FinCEN guidance on informal value transfer systems."
                ),
                recommended_action=RecommendedAction.ENHANCED_MONITORING,
                priority=priority,
                status=AlertStatus.NEW,
                created_at=now,
            )
        )

    # Check payout combined with recipient's other activity
    if (
        payout_amount is not None
        and payout_recipient_id is not None
        and (payout_amount + payout_recipient_daily_total) >= config.ctr.ctr_threshold
    ):
        alerts.append(
            ComplianceAlert(
                alert_id=str(uuid.uuid4()),
                alert_type=AlertType.CTR_THRESHOLD,
                user_id=payout_recipient_id,
                transaction_ids=[],
                amount_total=payout_amount + payout_recipient_daily_total,
                description=(
                    f"Circle {circle_id} payout of ${payout_amount:,.2f} to user "
                    f"{payout_recipient_id}, combined with the recipient's other "
                    f"daily activity (${payout_recipient_daily_total:,.2f}), "
                    f"totals ${payout_amount + payout_recipient_daily_total:,.2f} "
                    f"which meets or exceeds the CTR threshold."
                ),
                regulatory_basis=(
                    "31 CFR § 1010.311 — CTR aggregation across transaction "
                    "types including circle payouts."
                ),
                recommended_action=RecommendedAction.FILE_CTR,
                priority=AlertPriority.URGENT,
                status=AlertStatus.NEW,
                created_at=now,
            )
        )

    # Check members with existing compliance alerts
    if config.circle.flag_circles_with_alerted_members and members_with_alerts:
        alerts.append(
            ComplianceAlert(
                alert_id=str(uuid.uuid4()),
                alert_type=AlertType.EDD_TRIGGER,
                user_id=f"circle:{circle_id}",
                transaction_ids=[],
                amount_total=member_contributions_total,
                description=(
                    f"Circle {circle_id} has {len(members_with_alerts)} member(s) "
                    f"under existing compliance alerts: "
                    f"{', '.join(members_with_alerts)}. Circle requires "
                    f"enhanced monitoring."
                ),
                regulatory_basis=(
                    "31 CFR § 1022.210(d) — Risk-based monitoring of related "
                    "accounts and relationships. Enhanced due diligence for "
                    "circle participants associated with compliance alerts."
                ),
                recommended_action=RecommendedAction.ENHANCED_MONITORING,
                priority=AlertPriority.ELEVATED,
                status=AlertStatus.NEW,
                created_at=now,
            )
        )

    # Check payout exceeding monitoring threshold
    if payout_amount is not None and payout_amount >= config.circle.payout_monitoring_threshold:
        alerts.append(
            ComplianceAlert(
                alert_id=str(uuid.uuid4()),
                alert_type=AlertType.SUSPICIOUS_ACTIVITY,
                user_id=payout_recipient_id or f"circle:{circle_id}",
                transaction_ids=[],
                amount_total=payout_amount,
                description=(
                    f"Circle {circle_id} payout of ${payout_amount:,.2f} exceeds "
                    f"the ${config.circle.payout_monitoring_threshold:,.0f} "
                    f"monitoring threshold."
                ),
                regulatory_basis=(
                    "FinCEN guidance on IVTS monitoring — large payouts from "
                    "rotating savings circles require enhanced scrutiny."
                ),
                recommended_action=RecommendedAction.ENHANCED_MONITORING,
                priority=AlertPriority.ROUTINE,
                status=AlertStatus.NEW,
                created_at=now,
            )
        )

    return alerts


# ---------------------------------------------------------------------------
# Aggregate monitor: run all rules on a transaction
# ---------------------------------------------------------------------------


class ComplianceMonitor:
    """Orchestrates all BSA/AML monitoring rules against transactions."""

    def __init__(self, config: ComplianceConfig | None = None) -> None:
        self.config = config or default_config

    def evaluate_transaction(
        self,
        transaction: ComplianceTransaction,
        daily_total: float = 0.0,
        daily_transaction_ids: list[str] | None = None,
        round_amount_ratio_30d: float | None = None,
        received_transactions: list[ComplianceTransaction] | None = None,
        sent_transactions: list[ComplianceTransaction] | None = None,
        tx_count_24h: int = 0,
        tx_amount_mean_30d: float = 0.0,
        tx_amount_std_30d: float = 0.0,
        tx_cumulative_7d: float = 0.0,
        last_known_country: str | None = None,
        distinct_countries_7d: int = 0,
    ) -> list[ComplianceAlert]:
        """Run all applicable monitoring rules on a single transaction.

        Returns all generated compliance alerts.
        """
        all_alerts: list[ComplianceAlert] = []

        # Include current transaction in daily total
        effective_daily_total = daily_total + transaction.amount
        effective_daily_ids = (daily_transaction_ids or []) + [
            transaction.transaction_id
        ]

        # M-1: CTR threshold
        all_alerts.extend(
            check_ctr_threshold(
                user_id=transaction.user_id,
                daily_total=effective_daily_total,
                transaction_ids=effective_daily_ids,
                config=self.config,
            )
        )

        # M-2: Round amounts
        all_alerts.extend(
            check_round_amount(
                transaction=transaction,
                round_amount_ratio_30d=round_amount_ratio_30d,
                config=self.config,
            )
        )

        # M-3: Rapid movement
        if received_transactions or sent_transactions:
            all_alerts.extend(
                check_rapid_movement(
                    user_id=transaction.user_id,
                    received_transactions=received_transactions or [],
                    sent_transactions=sent_transactions or [],
                    config=self.config,
                )
            )

        # M-4: Unusual volume
        all_alerts.extend(
            check_unusual_volume(
                transaction=transaction,
                tx_count_24h=tx_count_24h,
                tx_amount_mean_30d=tx_amount_mean_30d,
                tx_amount_std_30d=tx_amount_std_30d,
                tx_cumulative_7d=tx_cumulative_7d,
                config=self.config,
            )
        )

        # M-5: Geographic risk
        all_alerts.extend(
            check_geographic_risk(
                transaction=transaction,
                last_known_country=last_known_country,
                distinct_countries_7d=distinct_countries_7d,
                config=self.config,
            )
        )

        if all_alerts:
            logger.info(
                "compliance_alerts_generated",
                user_id=transaction.user_id,
                transaction_id=transaction.transaction_id,
                alert_count=len(all_alerts),
                alert_types=[a.alert_type.value for a in all_alerts],
            )

        return all_alerts
