"""Dynamic customer risk scoring for Enhanced Due Diligence (Task 8.5).

Computes a composite risk score (0.0–1.0) from four factor categories:
  1. Transaction behavior (30%)
  2. Geographic factors (25%)
  3. Behavioral factors (25%)
  4. Circle participation factors (20%)

Risk levels:
  low       (0.0–0.3)  Standard monitoring, annual review
  medium    (0.3–0.6)  Enhanced monitoring, quarterly review
  high      (0.6–0.8)  EDD required, monthly review
  prohibited (0.8–1.0)  Account restricted pending investigation

Regulatory basis:
  31 CFR § 1022.210(d) — Risk-based AML program
  31 CFR § 1010.230 — Customer Due Diligence (CDD Rule)
  FinCEN Advisory FIN-2014-A007 — BSA/AML obligations for MSBs
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
    CustomerRiskAssessment,
    CustomerRiskProfile,
    RecommendedAction,
    RiskFactorDetail,
    RiskLevel,
    RiskScoreHistory,
)

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Individual factor scoring functions
# ---------------------------------------------------------------------------


def _score_transaction_factors(
    ctr_filing_count: int = 0,
    compliance_alert_count: int = 0,
    structuring_flag_count: int = 0,
    tx_volume_vs_baseline: float = 1.0,
    config: ComplianceConfig = default_config,
) -> list[RiskFactorDetail]:
    """Score transaction behavior factors.

    Regulatory basis: 31 CFR § 1022.210(d) — monitor transaction patterns
    relative to customer profile.
    """
    factors: list[RiskFactorDetail] = []

    # CTR filing history — multiple CTRs elevate baseline risk
    if ctr_filing_count > 0:
        ctr_score = min(1.0, ctr_filing_count * 0.15)
        factors.append(
            RiskFactorDetail(
                factor_name="ctr_filing_history",
                category="transaction",
                weight=0.25,
                score=ctr_score,
                description=(
                    f"{ctr_filing_count} CTR filing(s) on record. "
                    f"Multiple CTR filings elevate baseline risk per BSA monitoring guidelines."
                ),
            )
        )

    # Compliance alert history
    if compliance_alert_count > 0:
        alert_score = min(1.0, compliance_alert_count * 0.10)
        factors.append(
            RiskFactorDetail(
                factor_name="compliance_alert_history",
                category="transaction",
                weight=0.25,
                score=alert_score,
                description=(
                    f"{compliance_alert_count} compliance alert(s) on record "
                    f"(including dismissed alerts — patterns matter regardless "
                    f"of individual alert disposition)."
                ),
            )
        )

    # Structuring flag history
    if structuring_flag_count > 0:
        struct_score = min(1.0, structuring_flag_count * 0.25)
        factors.append(
            RiskFactorDetail(
                factor_name="structuring_history",
                category="transaction",
                weight=0.30,
                score=struct_score,
                description=(
                    f"{structuring_flag_count} structuring detection(s). "
                    f"Prior structuring flags significantly elevate risk "
                    f"per 31 USC § 5324."
                ),
            )
        )

    # Transaction volume relative to baseline
    if tx_volume_vs_baseline > 2.0:
        volume_score = min(1.0, (tx_volume_vs_baseline - 1.0) / 5.0)
        factors.append(
            RiskFactorDetail(
                factor_name="transaction_volume_anomaly",
                category="transaction",
                weight=0.20,
                score=volume_score,
                description=(
                    f"Transaction volume is {tx_volume_vs_baseline:.1f}x the "
                    f"established baseline."
                ),
            )
        )

    return factors


def _score_geographic_factors(
    high_risk_country_transactions: int = 0,
    third_country_transactions: int = 0,
    distinct_countries_30d: int = 1,
    config: ComplianceConfig = default_config,
) -> list[RiskFactorDetail]:
    """Score geographic risk factors.

    Regulatory basis: FATF Recommendation 19; 31 CFR § 1022.210(d)(4).
    """
    factors: list[RiskFactorDetail] = []

    if high_risk_country_transactions > 0:
        geo_score = min(1.0, high_risk_country_transactions * 0.30)
        factors.append(
            RiskFactorDetail(
                factor_name="high_risk_jurisdiction",
                category="geographic",
                weight=0.40,
                score=geo_score,
                description=(
                    f"{high_risk_country_transactions} transaction(s) involving "
                    f"FATF high-risk jurisdictions."
                ),
            )
        )

    if third_country_transactions > 0:
        third_score = min(1.0, third_country_transactions * 0.10)
        factors.append(
            RiskFactorDetail(
                factor_name="third_country_origin",
                category="geographic",
                weight=0.30,
                score=third_score,
                description=(
                    f"{third_country_transactions} transaction(s) from countries "
                    f"outside the expected US-HT corridor."
                ),
            )
        )

    if distinct_countries_30d > 3:
        country_score = min(1.0, (distinct_countries_30d - 3) * 0.15)
        factors.append(
            RiskFactorDetail(
                factor_name="geographic_diversity",
                category="geographic",
                weight=0.30,
                score=country_score,
                description=(
                    f"Transactions from {distinct_countries_30d} distinct countries "
                    f"in the past 30 days."
                ),
            )
        )

    return factors


def _score_behavioral_factors(
    account_age_days: int = 365,
    profile_complete: bool = True,
    fraud_score_avg: float = 0.0,
    ato_alert_count: int = 0,
    is_dormant_reactivated: bool = False,
    config: ComplianceConfig = default_config,
) -> list[RiskFactorDetail]:
    """Score behavioral risk factors.

    Regulatory basis: 31 CFR § 1010.230 — CDD Rule; FinCEN Advisory on
    account monitoring.
    """
    factors: list[RiskFactorDetail] = []

    # Account age — newer accounts = higher baseline risk
    if account_age_days < config.risk_scoring.new_account_days:
        age_score = 1.0 - (account_age_days / config.risk_scoring.new_account_days)
        factors.append(
            RiskFactorDetail(
                factor_name="new_account",
                category="behavioral",
                weight=0.20,
                score=age_score,
                description=(
                    f"Account is {account_age_days} days old "
                    f"(< {config.risk_scoring.new_account_days} day threshold). "
                    f"Newer accounts carry elevated baseline risk per standard "
                    f"BSA practice."
                ),
            )
        )

    # Profile completeness
    if not profile_complete:
        factors.append(
            RiskFactorDetail(
                factor_name="incomplete_profile",
                category="behavioral",
                weight=0.15,
                score=0.5,
                description=(
                    "Incomplete KYC documentation. Per 31 CFR § 1010.230, "
                    "incomplete customer identification increases risk."
                ),
            )
        )

    # Fraud score from Phase 3
    if fraud_score_avg > 0.3:
        factors.append(
            RiskFactorDetail(
                factor_name="elevated_fraud_score",
                category="behavioral",
                weight=0.25,
                score=min(1.0, fraud_score_avg),
                description=(
                    f"Average fraud score of {fraud_score_avg:.2f} from "
                    f"Phase 3 fraud detection module."
                ),
            )
        )

    # ATO alert history from Phase 7
    if ato_alert_count > 0:
        ato_score = min(1.0, ato_alert_count * 0.25)
        factors.append(
            RiskFactorDetail(
                factor_name="ato_alert_history",
                category="behavioral",
                weight=0.20,
                score=ato_score,
                description=(
                    f"{ato_alert_count} account takeover alert(s) from "
                    f"Phase 7 behavioral analytics."
                ),
            )
        )

    # Dormant account reactivation
    if is_dormant_reactivated:
        factors.append(
            RiskFactorDetail(
                factor_name="dormant_reactivation",
                category="behavioral",
                weight=0.20,
                score=0.6,
                description=(
                    "Previously dormant account suddenly reactivated. "
                    "Dormant-to-active transitions warrant elevated monitoring."
                ),
            )
        )

    return factors


def _score_circle_factors(
    circle_count: int = 0,
    flagged_circle_count: int = 0,
    max_payout_amount: float = 0.0,
    payout_to_contribution_ratio: float = 1.0,
    config: ComplianceConfig = default_config,
) -> list[RiskFactorDetail]:
    """Score circle participation risk factors.

    Regulatory basis: FinCEN guidance on IVTS monitoring.
    """
    factors: list[RiskFactorDetail] = []

    # Excessive circle participation
    if circle_count > 5:
        circle_score = min(1.0, (circle_count - 5) * 0.10)
        factors.append(
            RiskFactorDetail(
                factor_name="excessive_circle_participation",
                category="circle",
                weight=0.25,
                score=circle_score,
                description=(
                    f"Active in {circle_count} circles. Excessive circle "
                    f"participation may indicate misuse of the savings circle "
                    f"mechanism."
                ),
            )
        )

    # Membership in flagged circles
    if flagged_circle_count > 0:
        flagged_score = min(1.0, flagged_circle_count * 0.20)
        factors.append(
            RiskFactorDetail(
                factor_name="flagged_circle_membership",
                category="circle",
                weight=0.35,
                score=flagged_score,
                description=(
                    f"Member of {flagged_circle_count} circle(s) with "
                    f"compliance concerns or failing health scores."
                ),
            )
        )

    # Large payouts
    if max_payout_amount >= config.circle.payout_monitoring_threshold:
        payout_score = min(
            1.0,
            max_payout_amount / (config.ctr.ctr_threshold * 1.5),
        )
        factors.append(
            RiskFactorDetail(
                factor_name="large_circle_payout",
                category="circle",
                weight=0.25,
                score=payout_score,
                description=(
                    f"Maximum circle payout of ${max_payout_amount:,.2f} "
                    f"exceeds the ${config.circle.payout_monitoring_threshold:,.0f} "
                    f"monitoring threshold."
                ),
            )
        )

    # Anomalous payout-to-contribution ratio
    if payout_to_contribution_ratio > 2.0:
        ratio_score = min(1.0, (payout_to_contribution_ratio - 1.0) / 4.0)
        factors.append(
            RiskFactorDetail(
                factor_name="payout_contribution_imbalance",
                category="circle",
                weight=0.15,
                score=ratio_score,
                description=(
                    f"Payout-to-contribution ratio of "
                    f"{payout_to_contribution_ratio:.1f}x suggests potential "
                    f"circle mechanism abuse."
                ),
            )
        )

    return factors


# ---------------------------------------------------------------------------
# Composite Risk Scoring
# ---------------------------------------------------------------------------


def compute_risk_score(
    user_id: str,
    # Transaction factors
    ctr_filing_count: int = 0,
    compliance_alert_count: int = 0,
    structuring_flag_count: int = 0,
    tx_volume_vs_baseline: float = 1.0,
    # Geographic factors
    high_risk_country_transactions: int = 0,
    third_country_transactions: int = 0,
    distinct_countries_30d: int = 1,
    # Behavioral factors
    account_age_days: int = 365,
    profile_complete: bool = True,
    fraud_score_avg: float = 0.0,
    ato_alert_count: int = 0,
    is_dormant_reactivated: bool = False,
    # Circle factors
    circle_count: int = 0,
    flagged_circle_count: int = 0,
    max_payout_amount: float = 0.0,
    payout_to_contribution_ratio: float = 1.0,
    # Previous assessment
    previous_risk_level: RiskLevel | None = None,
    config: ComplianceConfig = default_config,
) -> CustomerRiskAssessment:
    """Compute the composite customer risk score.

    Combines all four factor categories using configured weights:
      transaction (30%) + geographic (25%) + behavioral (25%) + circle (20%)

    Returns a full CustomerRiskAssessment with factor details and risk level.
    """
    rc = config.risk_scoring

    # Score each category
    tx_factors = _score_transaction_factors(
        ctr_filing_count, compliance_alert_count, structuring_flag_count,
        tx_volume_vs_baseline, config,
    )
    geo_factors = _score_geographic_factors(
        high_risk_country_transactions, third_country_transactions,
        distinct_countries_30d, config,
    )
    behavioral_factors = _score_behavioral_factors(
        account_age_days, profile_complete, fraud_score_avg,
        ato_alert_count, is_dormant_reactivated, config,
    )
    circle_factors = _score_circle_factors(
        circle_count, flagged_circle_count, max_payout_amount,
        payout_to_contribution_ratio, config,
    )

    all_factors = tx_factors + geo_factors + behavioral_factors + circle_factors

    # Compute category scores (weighted average within each category)
    def _category_score(factors: list[RiskFactorDetail]) -> float:
        if not factors:
            return 0.0
        total_weight = sum(f.weight for f in factors)
        if total_weight == 0:
            return 0.0
        return sum(f.score * f.weight for f in factors) / total_weight

    tx_score = _category_score(tx_factors)
    geo_score = _category_score(geo_factors)
    beh_score = _category_score(behavioral_factors)
    circ_score = _category_score(circle_factors)

    # Composite score
    composite = (
        rc.transaction_weight * tx_score
        + rc.geographic_weight * geo_score
        + rc.behavioral_weight * beh_score
        + rc.circle_weight * circ_score
    )

    # Apply new account boost
    if account_age_days < rc.new_account_days:
        composite = min(1.0, composite + rc.new_account_risk_boost)

    composite = min(1.0, max(0.0, composite))

    # Determine risk level
    if composite <= rc.low_max:
        risk_level = RiskLevel.LOW
        review_days = rc.low_review_days
    elif composite <= rc.medium_max:
        risk_level = RiskLevel.MEDIUM
        review_days = rc.medium_review_days
    elif composite <= rc.high_max:
        risk_level = RiskLevel.HIGH
        review_days = rc.high_review_days
    else:
        risk_level = RiskLevel.PROHIBITED
        review_days = rc.high_review_days  # Same as high — requires immediate attention

    level_changed = previous_risk_level is not None and risk_level != previous_risk_level
    edd_required = risk_level in (RiskLevel.HIGH, RiskLevel.PROHIBITED)

    assessment = CustomerRiskAssessment(
        user_id=user_id,
        risk_score=composite,
        risk_level=risk_level,
        factor_details=all_factors,
        edd_required=edd_required,
        review_frequency_days=review_days,
        previous_risk_level=previous_risk_level,
        level_changed=level_changed,
        assessed_at=datetime.now(UTC),
    )

    logger.info(
        "risk_score_computed",
        user_id=user_id,
        risk_score=composite,
        risk_level=risk_level.value,
        edd_required=edd_required,
        factor_count=len(all_factors),
        level_changed=level_changed,
    )

    return assessment


# ---------------------------------------------------------------------------
# Customer Risk Manager
# ---------------------------------------------------------------------------


class CustomerRiskManager:
    """Manages customer risk profiles with history tracking and EDD triggers."""

    def __init__(self, config: ComplianceConfig | None = None) -> None:
        self.config = config or default_config
        # In-memory stores
        self._profiles: dict[str, CustomerRiskProfile] = {}
        self._history: dict[str, list[RiskScoreHistory]] = {}
        self._reviews: dict[str, list[dict]] = {}

    def assess_risk(self, user_id: str, **kwargs) -> tuple[CustomerRiskAssessment, list[ComplianceAlert]]:
        """Compute risk and generate alerts if EDD is triggered.

        Returns (assessment, alerts).
        """
        existing = self._profiles.get(user_id)
        previous_level = RiskLevel(existing.risk_level) if existing else None

        assessment = compute_risk_score(
            user_id=user_id,
            previous_risk_level=previous_level,
            config=self.config,
            **kwargs,
        )

        alerts: list[ComplianceAlert] = []

        # Update profile
        now = datetime.now(UTC)
        self._profiles[user_id] = CustomerRiskProfile(
            user_id=user_id,
            risk_level=assessment.risk_level,
            risk_score=assessment.risk_score,
            risk_factors=[f.factor_name for f in assessment.factor_details],
            edd_required=assessment.edd_required,
            last_reviewed=now,
            next_review_due=now + timedelta(days=assessment.review_frequency_days),
            review_frequency_days=assessment.review_frequency_days,
        )

        # Record history
        if user_id not in self._history:
            self._history[user_id] = []
        self._history[user_id].append(
            RiskScoreHistory(
                user_id=user_id,
                risk_score=assessment.risk_score,
                risk_level=assessment.risk_level,
                trigger_event=kwargs.get("trigger_event", "scheduled_assessment"),
                assessed_at=now,
            )
        )

        # EDD trigger: when risk level changes to high
        if assessment.level_changed and assessment.risk_level in (
            RiskLevel.HIGH,
            RiskLevel.PROHIBITED,
        ):
            alert = ComplianceAlert(
                alert_id=str(uuid.uuid4()),
                alert_type=AlertType.EDD_TRIGGER,
                user_id=user_id,
                transaction_ids=[],
                amount_total=0.0,
                description=(
                    f"Customer risk level escalated from "
                    f"{previous_level.value if previous_level else 'N/A'} to "
                    f"{assessment.risk_level.value}. "
                    f"Enhanced Due Diligence (EDD) is now required. "
                    f"Contributing factors: "
                    f"{', '.join(f.factor_name for f in assessment.factor_details)}."
                ),
                regulatory_basis=(
                    "31 CFR § 1010.230 — Customer Due Diligence (CDD Rule). "
                    "31 CFR § 1022.210(d) — Risk-based AML program requirement. "
                    "EDD required for high-risk customers per FinCEN guidance."
                ),
                recommended_action=RecommendedAction.ESCALATE_TO_BSA_OFFICER,
                priority=AlertPriority.CRITICAL,
                status=AlertStatus.NEW,
                created_at=now,
            )
            alerts.append(alert)

            logger.warning(
                "edd_triggered",
                user_id=user_id,
                previous_level=previous_level.value if previous_level else "N/A",
                new_level=assessment.risk_level.value,
                risk_score=assessment.risk_score,
            )

        return assessment, alerts

    def get_profile(self, user_id: str) -> CustomerRiskProfile | None:
        """Get the current risk profile for a customer."""
        return self._profiles.get(user_id)

    def get_high_risk_customers(self) -> list[CustomerRiskProfile]:
        """Get all high-risk and prohibited customers."""
        return [
            p
            for p in self._profiles.values()
            if p.risk_level in (RiskLevel.HIGH, RiskLevel.PROHIBITED)
        ]

    def get_history(self, user_id: str) -> list[RiskScoreHistory]:
        """Get risk score history for a customer."""
        return self._history.get(user_id, [])

    def record_review(
        self,
        user_id: str,
        reviewer: str,
        notes: str,
        new_risk_level: RiskLevel | None = None,
    ) -> CustomerRiskProfile | None:
        """Record a compliance officer's review of a customer's risk level.

        EDD downgrades require explicit officer review — once EDD is required,
        it stays required until a compliance officer explicitly downgrades.
        """
        profile = self._profiles.get(user_id)
        if not profile:
            return None

        now = datetime.now(UTC)

        # Record the review for audit trail
        if user_id not in self._reviews:
            self._reviews[user_id] = []
        self._reviews[user_id].append(
            {
                "reviewer": reviewer,
                "notes": notes,
                "reviewed_at": now.isoformat(),
                "previous_risk_level": profile.risk_level.value,
                "new_risk_level": new_risk_level.value if new_risk_level else profile.risk_level.value,
            }
        )

        # Apply new risk level if provided
        if new_risk_level:
            profile.risk_level = new_risk_level
            profile.edd_required = new_risk_level in (RiskLevel.HIGH, RiskLevel.PROHIBITED)

            # Update review frequency
            rc = self.config.risk_scoring
            if new_risk_level == RiskLevel.LOW:
                profile.review_frequency_days = rc.low_review_days
            elif new_risk_level == RiskLevel.MEDIUM:
                profile.review_frequency_days = rc.medium_review_days
            else:
                profile.review_frequency_days = rc.high_review_days

        profile.last_reviewed = now
        profile.next_review_due = now + timedelta(days=profile.review_frequency_days)

        # Record in history
        if user_id not in self._history:
            self._history[user_id] = []
        self._history[user_id].append(
            RiskScoreHistory(
                user_id=user_id,
                risk_score=profile.risk_score,
                risk_level=profile.risk_level,
                trigger_event=f"officer_review_by_{reviewer}",
                assessed_at=now,
            )
        )

        logger.info(
            "compliance_review_recorded",
            user_id=user_id,
            reviewer=reviewer,
            new_risk_level=profile.risk_level.value,
        )

        return profile

    def get_reviews(self, user_id: str) -> list[dict]:
        """Get all reviews for a customer (audit trail)."""
        return self._reviews.get(user_id, [])
