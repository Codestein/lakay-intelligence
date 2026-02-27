# Behavioral Analytics & Account Security — Validation Report

**Phase 7 | Lakay Intelligence**
**Date:** 2026-02-27
**Version:** behavior-profile-v1

---

## 1. Overview

This report documents the validation of the Phase 7 behavioral analytics and account security module. The module provides per-user behavioral profiling, session anomaly scoring across 5 dimensions, engagement lifecycle classification, and account takeover (ATO) detection for the Trebanx platform.

## 2. Scenario Validation Results

### Scenario A — Normal User, Normal Session

| Metric | Expected | Actual | Status |
|--------|----------|--------|--------|
| Anomaly score | < 0.3 | < 0.3 | PASS |
| Classification | normal | normal | PASS |
| ATO alert | None | None | PASS |
| Recommended action | none | none | PASS |

**Dimension breakdown:** All 5 dimensions score 0.0 — known device, known location, typical hour, normal actions, normal engagement.

### Scenario B — New Device, Otherwise Normal

| Metric | Expected | Actual | Status |
|--------|----------|--------|--------|
| Device anomaly | Elevated (0.3-0.5) | 0.5 (new device) | PASS |
| Composite score | 0.1-0.3 (suspicious range) | < 0.3 | PASS |
| ATO alert | None (single signal) | None | PASS |

**Key insight:** Single signal (new device) is insufficient for ATO alert. System correctly requires correlated signals.

### Scenario C — Classic ATO

| Metric | Expected | Actual | Status |
|--------|----------|--------|--------|
| Anomaly score | > 0.3 | > 0.5 | PASS |
| Classification | suspicious/high_risk/critical | suspicious+ | PASS |
| Contributing signals | 3+ | 4+ (anomaly, new device+location, sensitive actions, failed logins) | PASS |
| Recommended response | step_up or lock | step_up/lock | PASS |

**Dimension breakdown:**
- Temporal: High (3 AM login for 6-10 PM user)
- Device: High (new Android, user is iOS-only)
- Geographic: High (Lagos, NG — third country outside US/HT corridor)
- Behavioral: High (sensitive actions, bot-like speed)
- Engagement: Moderate

### Scenario D — Impossible Travel ATO

| Metric | Expected | Actual | Status |
|--------|----------|--------|--------|
| Geographic anomaly | Maxed (≥ 0.9) | 0.9+ | PASS |
| Impossible travel detected | Yes | Yes | PASS |
| ATO signal | impossible_travel present | Present | PASS |

### Scenario E — Gradual Account Compromise

| Metric | Expected | Actual | Status |
|--------|----------|--------|--------|
| Initial session | Normal/Suspicious | Normal/Suspicious | PASS |
| With sensitive actions | Escalated | Escalated to suspicious+ | PASS |

**Key insight:** System catches slow-burn ATOs by detecting behavioral anomalies (sensitive actions) even when device/geo are mildly suspicious.

### Scenario F — Legitimate Haiti Travel

| Metric | Expected | Actual | Status |
|--------|----------|--------|--------|
| Known HT location | Score 0.0 for known user | 0.0 | PASS |
| New HT location (corridor) | Geo anomaly < 0.4 | < 0.4 | PASS |
| Overall classification | Normal/Suspicious (not high_risk) | Normal | PASS |

**Haiti corridor awareness:** The system correctly recognizes that US ↔ HT travel is normal for Trebanx's Haitian diaspora users. Geographic anomaly is reduced by the `corridor_reduction` factor (0.4) for countries in the `corridor_countries` set (US, HT).

### Scenario G — New User (Building Profile)

| Metric | Expected | Actual | Status |
|--------|----------|--------|--------|
| Profile status | building | building | PASS |
| Profile maturity | 3 | 3 | PASS |
| Score reduction | 0.6x multiplier applied | Applied | PASS |
| ATO alert | None (unless extreme) | None | PASS |

**Key insight:** Building profiles (< 10 sessions) get a 0.6x multiplier on composite scores, preventing false positives during onboarding.

## 3. Latency Measurements

| Operation | Target | Measured (p50) | Status |
|-----------|--------|----------------|--------|
| Normal session scoring | < 100ms | < 5ms | PASS |
| Full ATO assessment | < 1000ms | < 10ms | PASS |
| Anomalous → alert pipeline | < 30s | < 50ms (without I/O) | PASS |

**Note:** Latency measurements exclude actual database and Kafka I/O, which are mocked in tests. Production latency will be higher but well within the 30-second target given PostgreSQL query times (< 50ms) and Kafka publish times (< 100ms).

## 4. False Positive / False Negative Analysis

### False Positive Rate (100 Normal Sessions)

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| False alerts (high_risk/critical) | 0 | 0 | PASS |
| False suspicious | 0 | 0 | PASS |

### Detection Rate (20 Anomalous Sessions)

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| Detected (suspicious+) | 100% (20/20) | 100% (20/20) | PASS |

## 5. Scoring Dimension Analysis

### Weight Distribution

| Dimension | Weight | Rationale |
|-----------|--------|-----------|
| Temporal | 0.15 | Time alone is a weak signal (jet lag, schedule changes) |
| Device | 0.25 | Strong ATO indicator — most users have 1-3 devices |
| Geographic | 0.25 | Strong ATO indicator — especially outside US/HT corridor |
| Behavioral | 0.25 | Action patterns reveal intent (sensitive actions, speed) |
| Engagement | 0.10 | Context signal — dormancy spikes and feature novelty |

### Correlation Boosting (ATO Pipeline)

| Signals | Multiplier | Effect |
|---------|-----------|--------|
| 1 signal | 1.0x | Moderate risk at most |
| 2 correlated signals | 1.5x | High risk possible |
| 3+ correlated signals | 2.0x | Critical risk likely |

This correlation model ensures that individual signals (new device, unusual hour) remain low-risk, but combinations (new device + new location + sensitive actions) are flagged as critical.

## 6. Adaptive Profile Behavior

### Exponential Moving Average (EMA)

- **Decay rate (α):** 0.15 (default)
- **Effect:** Profiles adapt to gradual behavior changes over ~15-20 sessions
- **Example:** User moves from Boston to Miami → geographic baseline shifts naturally over 2-3 weeks

### Staleness

- **Threshold:** 30 days of inactivity
- **Effect:** Stale profiles use 0.8x score multiplier and 1.5x tolerance bands
- **Recovery:** Profile returns to active status after sufficient new sessions

### New User Protection

- **Minimum sessions:** 10 sessions over ≥ 7 distinct days
- **Effect:** Building profiles use 0.6x score multiplier and 2.0x tolerance bands
- **Rationale:** Prevents false positives during the critical onboarding period

## 7. Engagement Lifecycle Coverage

| Stage | Criteria | Users Covered |
|-------|----------|---------------|
| new | ≤ 5 sessions, joined < 14 days | First-time users |
| onboarding | 5-15 sessions, exploring features | Learning the platform |
| active | Regular usage matching personal baseline | Core user base |
| power_user | High frequency, multiple features | Community leaders |
| declining | Engagement dropping over 3 weeks | At-risk for churn |
| dormant | No activity 14-30 days | Inactive but recoverable |
| churned | No activity 30+ days | Lost users |
| reactivated | Returned after dormancy | Win-back users |

## 8. Cross-Domain Integration

| Integration | Status | Mechanism |
|-------------|--------|-----------|
| Fraud pipeline notification | Implemented | Structured log event on ATO alert |
| Circle health notification | Implemented | Structured log event on ATO alert |
| Kafka ATO alerts | Implemented | Published to `lakay.behavior.ato-alerts` |

## 9. Recommendations for Threshold Tuning

1. **Temporal weight (0.15 → 0.10):** Consider reducing after real-data analysis if users frequently login at varied hours
2. **Corridor countries:** Monitor for users traveling to Dominican Republic (DR) — may need to add DR to the corridor
3. **Building profile multiplier (0.6x):** May need adjustment based on new-user false positive rates in production
4. **EMA decay rate (0.15):** Users who travel frequently may need a higher alpha (faster adaptation)
5. **Churn score drop threshold (20 points):** Calibrate against actual churn events once Trebanx has sufficient user data

## 10. Test Coverage Summary

| Test Suite | Tests | Status |
|-----------|-------|--------|
| Config validation | 8 | PASS |
| Profile engine | 12 | PASS |
| Session anomaly scoring | 22 | PASS |
| Engagement scoring | 16 | PASS |
| ATO detection pipeline | 14 | PASS |
| E2E scenarios (A-G) | 14 | PASS |
| Latency validation | 2 | PASS |
| Volume testing | 2 | PASS |
| **Total** | **90** | **ALL PASS** |
