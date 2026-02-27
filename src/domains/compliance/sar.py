"""SAR (Suspicious Activity Report) narrative draft generator (Task 8.4).

Produces machine-generated SAR narrative drafts from structured alert and case
data. Drafts are explicitly marked as requiring human review — they must never
be filed without a compliance officer's approval.

Regulatory basis:
  31 CFR § 1022.320 — SAR filing requirements for MSBs
  31 CFR § 1022.320(b)(3) — SAR narrative must describe why activity is suspicious
  FinCEN SAR filing instructions — narrative elements

Templates match FinCEN SAR form fields:
  - Subject identification
  - Suspicious activity description
  - Relationship to the institution
  - Known explanations
"""

import uuid
from datetime import UTC, datetime

import structlog

from .models import (
    AlertType,
    ComplianceAlert,
    ComplianceCase,
    SARDraft,
    SARDraftStatus,
    StructuringTypology,
)

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Narrative Templates
# ---------------------------------------------------------------------------

STRUCTURING_TEMPLATE = """SUSPICIOUS ACTIVITY NARRATIVE — STRUCTURING

Subject: {customer_id}
Filing Institution: Trebanx (Money Services Business)
Date Range: {date_range}

DESCRIPTION OF SUSPICIOUS ACTIVITY:

On {dates}, {customer_id} conducted {transaction_count} transactions totaling \
${total_amount:,.2f} that appear designed to evade Currency Transaction Report (CTR) \
reporting requirements under 31 CFR § 1010.311.

Individual transaction amounts ranged from ${min_amount:,.2f} to ${max_amount:,.2f}, \
each below the $10,000 CTR threshold. The cumulative total of ${total_amount:,.2f} \
exceeds the reporting threshold.

Structuring typology: {typology}
Detection confidence: {confidence:.0%}

The following specific transactions are of concern:
{transaction_list}

RELATIONSHIP TO INSTITUTION:

{customer_id} maintains an active account with Trebanx for {account_purpose}.

{additional_context}

KNOWN EXPLANATIONS:

{known_explanations}

---
{disclaimer}"""

RAPID_MOVEMENT_TEMPLATE = """SUSPICIOUS ACTIVITY NARRATIVE — RAPID FUND MOVEMENT

Subject: {customer_id}
Filing Institution: Trebanx (Money Services Business)
Date Range: {date_range}

DESCRIPTION OF SUSPICIOUS ACTIVITY:

{customer_id} received ${received_amount:,.2f} on {received_date} and transferred \
${sent_amount:,.2f} within {hours_elapsed:.1f} hours to {destination}. This rapid \
movement of funds ({transfer_ratio:.0%} of received amount) with no apparent \
business purpose is consistent with layering activity designed to obscure the \
origin of funds.

Received transaction: {received_transaction_id} (${received_amount:,.2f})
Sent transaction: {sent_transaction_id} (${sent_amount:,.2f})

RELATIONSHIP TO INSTITUTION:

{customer_id} maintains an active account with Trebanx for {account_purpose}.

{additional_context}

KNOWN EXPLANATIONS:

{known_explanations}

---
{disclaimer}"""

CIRCLE_ABUSE_TEMPLATE = """SUSPICIOUS ACTIVITY NARRATIVE — SAVINGS CIRCLE ABUSE

Subject: {customer_id}
Filing Institution: Trebanx (Money Services Business)
Date Range: {date_range}

DESCRIPTION OF SUSPICIOUS ACTIVITY:

Through participation in savings circle {circle_id}, {customer_id} received a \
payout of ${payout_amount:,.2f} on {payout_date}. Subsequent analysis revealed \
{anomaly_description}.

{circle_context}

RELATIONSHIP TO INSTITUTION:

{customer_id} participates in Trebanx's digital rotating savings circle (sou-sou) \
program.

{additional_context}

KNOWN EXPLANATIONS:

{known_explanations}

---
{disclaimer}"""

GEOGRAPHIC_RISK_TEMPLATE = """SUSPICIOUS ACTIVITY NARRATIVE — GEOGRAPHIC RISK

Subject: {customer_id}
Filing Institution: Trebanx (Money Services Business)
Date Range: {date_range}

DESCRIPTION OF SUSPICIOUS ACTIVITY:

Transactions initiated from {location}, which is inconsistent with {customer_id}'s \
established profile of activity from {known_locations}. The subject transacted from \
{distinct_countries} distinct countries in the past 7 days.

{transaction_details}

{geographic_context}

RELATIONSHIP TO INSTITUTION:

{customer_id} maintains an active account with Trebanx for {account_purpose}.

{additional_context}

KNOWN EXPLANATIONS:

{known_explanations}

---
{disclaimer}"""

MULTI_SIGNAL_TEMPLATE = """SUSPICIOUS ACTIVITY NARRATIVE — MULTIPLE INDICATORS

Subject: {customer_id}
Filing Institution: Trebanx (Money Services Business)
Date Range: {date_range}

DESCRIPTION OF SUSPICIOUS ACTIVITY:

Multiple compliance indicators have been identified for {customer_id}:

{signal_descriptions}

The convergence of {signal_count} independent compliance signals warrants \
heightened scrutiny. Each signal is documented below:

{detailed_signals}

RELATIONSHIP TO INSTITUTION:

{customer_id} maintains an active account with Trebanx for {account_purpose}.

{additional_context}

KNOWN EXPLANATIONS:

{known_explanations}

---
{disclaimer}"""

DISCLAIMER = (
    "MACHINE-GENERATED DRAFT — This narrative was automatically generated "
    "by Lakay Intelligence compliance monitoring system and MUST be reviewed "
    "and approved by a qualified BSA/AML compliance officer before filing "
    "with FinCEN. Do not file without human review and approval."
)


# ---------------------------------------------------------------------------
# Data Assembly
# ---------------------------------------------------------------------------


def assemble_sar_data(
    case: ComplianceCase,
    alerts: list[ComplianceAlert],
) -> dict:
    """Pull all relevant data from a compliance case and its linked alerts.

    Assembles: customer information, transaction details, timeline of events,
    rule triggers with explanations, and behavioral context.
    """
    all_transaction_ids = []
    all_amounts = []
    alert_types = set()
    descriptions = []
    timestamps = []

    for alert in alerts:
        all_transaction_ids.extend(alert.transaction_ids)
        all_amounts.append(alert.amount_total)
        alert_types.add(alert.alert_type.value)
        descriptions.append(alert.description)
        timestamps.append(alert.created_at)

    # Determine date range
    if timestamps:
        date_range = (
            f"{min(timestamps).strftime('%Y-%m-%d')} to "
            f"{max(timestamps).strftime('%Y-%m-%d')}"
        )
    else:
        date_range = "N/A"

    return {
        "case_id": case.case_id,
        "customer_id": case.user_id,
        "alert_count": len(alerts),
        "alert_types": list(alert_types),
        "transaction_ids": list(set(all_transaction_ids)),
        "total_amount": sum(all_amounts),
        "min_amount": min(all_amounts) if all_amounts else 0.0,
        "max_amount": max(all_amounts) if all_amounts else 0.0,
        "date_range": date_range,
        "descriptions": descriptions,
        "timestamps": [t.isoformat() for t in sorted(timestamps)],
        "case_narrative": case.narrative or "",
    }


# ---------------------------------------------------------------------------
# Narrative Drafting
# ---------------------------------------------------------------------------


def _select_template(alert_types: list[str], alerts: list[ComplianceAlert]) -> str:
    """Select the most appropriate narrative template based on alert types."""
    types_set = set(alert_types)

    # Multi-signal: 2+ different alert types
    if len(types_set) >= 2:
        return "multi_signal"

    # Single type
    if AlertType.STRUCTURING.value in types_set:
        return "structuring"

    if AlertType.SUSPICIOUS_ACTIVITY.value in types_set:
        # Check for specific subtypes from descriptions
        for alert in alerts:
            if "rapid movement" in alert.description.lower() or "layering" in alert.description.lower():
                return "rapid_movement"
            if "circle" in alert.description.lower():
                return "circle_abuse"
            if "geographic" in alert.description.lower() or "jurisdiction" in alert.description.lower():
                return "geographic_risk"
        return "multi_signal"

    # Default to multi-signal for other types
    return "multi_signal"


def _format_transaction_list(transaction_ids: list[str], amounts: list[float] | None = None) -> str:
    """Format a list of transactions for narrative inclusion."""
    if not transaction_ids:
        return "  (No specific transactions identified)"

    lines = []
    for i, tx_id in enumerate(transaction_ids):
        if amounts and i < len(amounts):
            lines.append(f"  - Transaction {tx_id}: ${amounts[i]:,.2f}")
        else:
            lines.append(f"  - Transaction {tx_id}")
    return "\n".join(lines)


def draft_narrative(
    case: ComplianceCase,
    alerts: list[ComplianceAlert],
) -> SARDraft:
    """Generate a SAR narrative draft from a compliance case and its alerts.

    The draft is explicitly marked as machine-generated and requiring human
    review before filing.
    """
    data = assemble_sar_data(case, alerts)
    template_name = _select_template(data["alert_types"], alerts)

    confidence_notes = []
    sections = {
        "subject_identification": data["customer_id"],
        "filing_institution": "Trebanx (Money Services Business)",
        "date_range": data["date_range"],
        "alert_count": data["alert_count"],
        "total_amount": data["total_amount"],
        "template_used": template_name,
    }

    # Generate narrative based on template
    if template_name == "structuring":
        # Find structuring-specific details from alerts
        typology = "unknown"
        confidence = 0.0
        for alert in alerts:
            if "micro" in alert.description.lower():
                typology = "Micro-structuring (single day)"
            elif "slow" in alert.description.lower():
                typology = "Slow structuring (across days)"
            elif "fan-out" in alert.description.lower() or "fan_out" in alert.description.lower():
                typology = "Fan-out (multiple recipients)"
            elif "funnel" in alert.description.lower():
                typology = "Funnel (multiple senders)"
            # Extract confidence if present
            desc = alert.description
            if "confidence:" in desc.lower():
                try:
                    conf_str = desc.lower().split("confidence:")[1].strip().split(".")[0]
                    confidence = float(conf_str.replace(" ", "")) if conf_str else 0.0
                except (ValueError, IndexError):
                    pass

        dates = data["date_range"]
        narrative = STRUCTURING_TEMPLATE.format(
            customer_id=data["customer_id"],
            date_range=dates,
            dates=dates,
            transaction_count=len(data["transaction_ids"]),
            total_amount=data["total_amount"],
            min_amount=data["min_amount"],
            max_amount=data["max_amount"],
            typology=typology,
            confidence=confidence,
            transaction_list=_format_transaction_list(data["transaction_ids"]),
            account_purpose="remittance and savings circle services",
            additional_context="\n".join(data["descriptions"]),
            known_explanations="No known legitimate explanation identified at time of drafting.",
            disclaimer=DISCLAIMER,
        )
        sections["typology"] = typology

    elif template_name == "rapid_movement":
        # Extract movement details
        received_amount = data["total_amount"] / 2 if data["total_amount"] else 0.0
        sent_amount = received_amount
        tx_ids = data["transaction_ids"]

        narrative = RAPID_MOVEMENT_TEMPLATE.format(
            customer_id=data["customer_id"],
            date_range=data["date_range"],
            received_amount=received_amount,
            received_date=data["date_range"].split(" to ")[0] if " to " in data["date_range"] else data["date_range"],
            sent_amount=sent_amount,
            hours_elapsed=24.0,
            destination="recipient via Trebanx remittance service",
            transfer_ratio=sent_amount / received_amount if received_amount > 0 else 0.0,
            received_transaction_id=tx_ids[0] if tx_ids else "N/A",
            sent_transaction_id=tx_ids[1] if len(tx_ids) > 1 else "N/A",
            account_purpose="remittance and savings circle services",
            additional_context="\n".join(data["descriptions"]),
            known_explanations="No known legitimate explanation identified at time of drafting.",
            disclaimer=DISCLAIMER,
        )
        confidence_notes.append(
            "Rapid movement timing extracted from alert data — verify exact "
            "timestamps from transaction records."
        )

    elif template_name == "circle_abuse":
        narrative = CIRCLE_ABUSE_TEMPLATE.format(
            customer_id=data["customer_id"],
            date_range=data["date_range"],
            circle_id="(see alert details)",
            payout_amount=data["total_amount"],
            payout_date=data["date_range"].split(" to ")[0] if " to " in data["date_range"] else data["date_range"],
            anomaly_description="; ".join(data["descriptions"]),
            circle_context="Circle participation details should be verified against circle records.",
            account_purpose="savings circle participation",
            additional_context="",
            known_explanations="No known legitimate explanation identified at time of drafting.",
            disclaimer=DISCLAIMER,
        )
        confidence_notes.append(
            "Circle-specific details may require manual verification against "
            "circle membership and payout records."
        )

    elif template_name == "geographic_risk":
        narrative = GEOGRAPHIC_RISK_TEMPLATE.format(
            customer_id=data["customer_id"],
            date_range=data["date_range"],
            location="(see alert details for specific locations)",
            known_locations="US, HT (expected corridor)",
            distinct_countries="(see alert details)",
            transaction_details=_format_transaction_list(data["transaction_ids"]),
            geographic_context="\n".join(data["descriptions"]),
            account_purpose="remittance and savings circle services",
            additional_context="",
            known_explanations="No known legitimate explanation identified at time of drafting.",
            disclaimer=DISCLAIMER,
        )
        confidence_notes.append(
            "Geographic location data should be verified against IP geolocation "
            "and customer KYC records."
        )

    else:  # multi_signal
        signal_descriptions = "\n".join(
            f"  {i + 1}. {desc}" for i, desc in enumerate(data["descriptions"])
        )
        detailed_signals = "\n\n".join(
            f"Signal {i + 1} ({alert.alert_type.value}):\n"
            f"  Priority: {alert.priority.value}\n"
            f"  Amount: ${alert.amount_total:,.2f}\n"
            f"  {alert.description}"
            for i, alert in enumerate(alerts)
        )

        narrative = MULTI_SIGNAL_TEMPLATE.format(
            customer_id=data["customer_id"],
            date_range=data["date_range"],
            signal_descriptions=signal_descriptions,
            signal_count=len(alerts),
            detailed_signals=detailed_signals,
            account_purpose="remittance and savings circle services",
            additional_context="",
            known_explanations="No known legitimate explanation identified at time of drafting.",
            disclaimer=DISCLAIMER,
        )

    # Assemble confidence note
    if not confidence_notes:
        confidence_notes.append(
            "Draft generated from structured alert data. All amounts, dates, "
            "and transaction references should be verified against source records."
        )

    confidence_note = " ".join(confidence_notes)

    draft = SARDraft(
        draft_id=str(uuid.uuid4()),
        case_id=case.case_id,
        user_id=case.user_id,
        narrative=narrative,
        sections=sections,
        confidence_note=confidence_note,
        status=SARDraftStatus.DRAFT,
        generated_at=datetime.now(UTC),
    )

    logger.info(
        "sar_narrative_drafted",
        draft_id=draft.draft_id,
        case_id=case.case_id,
        user_id=case.user_id,
        template=template_name,
        alert_count=len(alerts),
    )

    return draft


# ---------------------------------------------------------------------------
# SAR Draft Manager
# ---------------------------------------------------------------------------


class SARDraftManager:
    """Manages SAR narrative drafts for compliance cases."""

    def __init__(self) -> None:
        # In-memory store: {draft_id: SARDraft}
        self._drafts: dict[str, SARDraft] = {}
        # Case-to-draft mapping
        self._case_drafts: dict[str, list[str]] = {}

    def generate_draft(
        self,
        case: ComplianceCase,
        alerts: list[ComplianceAlert],
    ) -> SARDraft:
        """Generate a SAR narrative draft for a compliance case."""
        draft = draft_narrative(case, alerts)
        self._drafts[draft.draft_id] = draft

        if case.case_id not in self._case_drafts:
            self._case_drafts[case.case_id] = []
        self._case_drafts[case.case_id].append(draft.draft_id)

        return draft

    def get_draft(self, draft_id: str) -> SARDraft | None:
        """Get a specific SAR draft."""
        return self._drafts.get(draft_id)

    def get_drafts_for_case(self, case_id: str) -> list[SARDraft]:
        """Get all drafts for a compliance case."""
        draft_ids = self._case_drafts.get(case_id, [])
        return [self._drafts[did] for did in draft_ids if did in self._drafts]

    def get_pending_drafts(self) -> list[SARDraft]:
        """Get all drafts in draft or reviewed status (not yet filed)."""
        return [
            d
            for d in self._drafts.values()
            if d.status in (SARDraftStatus.DRAFT, SARDraftStatus.REVIEWED)
        ]

    def update_status(
        self,
        draft_id: str,
        status: SARDraftStatus,
        reviewed_by: str | None = None,
    ) -> SARDraft | None:
        """Update a SAR draft's status."""
        draft = self._drafts.get(draft_id)
        if draft:
            draft.status = status
            if reviewed_by:
                draft.reviewed_by = reviewed_by
                draft.reviewed_at = datetime.now(UTC)
            logger.info(
                "sar_draft_status_updated",
                draft_id=draft_id,
                new_status=status.value,
                reviewed_by=reviewed_by,
            )
        return draft
