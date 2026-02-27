# Bias Audit Template

> Lakay Intelligence -- Phase 10, Task 10.5
> Last updated: 2026-02-27

This document provides a structured template for auditing model fairness across
all scoring models in the Lakay Intelligence system. It is designed for the
Trebanx remittance platform context, with particular attention to the Haitian
diaspora user base.

**Status:** Template ready. Execution pending availability of real demographic
data. The current training dataset (PaySim synthetic) does not contain
demographic attributes, so disparate impact analysis cannot be performed until
production data with demographic fields is available.

---

## 1. Audit Scope

### 1.1 Models Subject to Bias Audit

| Model | Priority | Rationale |
|---|---|---|
| fraud-detector-v0.2 (XGBoost) | **Critical** | ML model with opaque decision boundaries; directly impacts transaction approval |
| Compliance Risk Scorer v1 | High | Determines EDD requirements and account restrictions; regulatory implications |
| Behavioral Anomaly Scorer v1 | High | Session termination and challenge actions affect user access |
| Circle Health Scorer v1 | Medium | Affects circle status but does not directly restrict individual users |

### 1.2 Protected Attributes

The following attributes must be evaluated for disparate impact. Note that these
are not currently collected in the synthetic training data and will need to be
sourced from production KYC/demographic data when available.

| Attribute | Proxy Risk | Notes |
|---|---|---|
| National origin / ethnicity | High | Haitian diaspora is the primary user base |
| Remittance corridor | High | US-to-Haiti corridor may correlate with national origin |
| Geographic location | Medium | IP geolocation, city, country of transaction origin |
| Language preference | Medium | Haitian Creole vs English vs French |
| Account age | Low | Newer accounts may correlate with recent immigrant status |
| Transaction amount patterns | Medium | Round-amount remittances common in Haitian diaspora |

---

## 2. Methodology

### 2.1 Fairness Metrics

Each audit must evaluate the following metrics across protected groups:

#### 2.1.1 Disparate Impact Ratio (Four-Fifths Rule)

The primary regulatory standard for adverse impact analysis.

```
Disparate Impact Ratio = (Selection Rate for Protected Group) / (Selection Rate for Reference Group)
```

| Threshold | Interpretation | Action |
|---|---|---|
| >= 0.80 (4/5ths) | No adverse impact detected | Document and proceed |
| 0.60 - 0.79 | Marginal adverse impact | Investigate root causes; consider mitigation |
| < 0.60 | Significant adverse impact | **Mandatory remediation** before deployment |

**For fraud detection context:** "Selection rate" = rate at which a group's
transactions are NOT flagged as fraudulent (i.e., the approval rate). A lower
approval rate for a protected group indicates potential bias.

#### 2.1.2 Equalized Odds

The model should have similar True Positive Rates (TPR) and False Positive
Rates (FPR) across protected groups.

```
TPR Parity:  |TPR_protected - TPR_reference| < threshold
FPR Parity:  |FPR_protected - FPR_reference| < threshold
```

| Metric | Acceptable Threshold | Notes |
|---|---|---|
| TPR difference | < 0.05 | Model catches fraud equally across groups |
| FPR difference | < 0.05 | Model does not over-flag one group compared to another |

#### 2.1.3 Demographic Parity

The positive prediction rate should be similar across groups, regardless of
the actual fraud rate.

```
Demographic Parity Gap = |P(Y_hat=1 | G=protected) - P(Y_hat=1 | G=reference)|
```

| Threshold | Interpretation |
|---|---|
| < 0.05 | Acceptable parity |
| 0.05 - 0.10 | Investigate; may be justified by differing base rates |
| > 0.10 | Remediation required |

**Note:** Demographic parity may conflict with equalized odds when base fraud
rates genuinely differ across groups. In such cases, equalized odds is the
preferred metric, with documentation of the base rate difference.

### 2.2 Trebanx-Specific Bias Concerns

The following patterns are common and legitimate in the Haitian diaspora user
base. The fraud detection model must not disproportionately flag these patterns:

#### 2.2.1 Remittance Corridor Patterns (US to Haiti)

| Pattern | Legitimate Reason | Bias Risk |
|---|---|---|
| Regular recurring transfers to Haiti | Family support, recurring obligations | May trigger velocity rules |
| Round-amount transfers ($100, $200, $500) | Cultural norm for remittances | May appear "structured" |
| Transfers timed around holidays or events | Fete Champetre, Christmas, school start | May trigger temporal anomaly |
| Multiple recipients in Haiti | Extended family support | May trigger fan-out velocity rules |

**Audit check:** Compare fraud flag rates for US-to-HT corridor transactions
against same-amount domestic transactions. The corridor itself should not be a
risk factor.

#### 2.2.2 Savings Circle (Sou-Sou / Min) Patterns

| Pattern | Legitimate Reason | Bias Risk |
|---|---|---|
| Regular fixed-amount contributions | Circle participation | May appear as structured transactions |
| Periodic large payouts | Circle rotation payout | May trigger large-amount alerts |
| Group of users transacting together | Circle members contributing | May trigger coordinated behavior flags |

**Audit check:** Circle-related transactions should not have a higher false
positive rate than non-circle transactions of similar amounts.

#### 2.2.3 Geographic and Location Patterns

| Pattern | Legitimate Reason | Bias Risk |
|---|---|---|
| Transactions from areas with high Haitian diaspora populations (Miami, NYC, Boston) | User location | Geographic concentration should not increase risk |
| IP addresses from Haiti during visits | Travel to home country | Should not trigger impossible travel if within reasonable time |
| VPN usage | Privacy preference, accessing home-country content | Should not automatically elevate risk |

---

## 3. Data Requirements

### 3.1 Demographic Data Needed

To execute a bias audit, the following data must be collected or derived:

| Data Field | Source | Privacy Considerations |
|---|---|---|
| Country of origin | KYC data | PII; must be handled under data governance policy |
| Primary remittance corridor | Transaction history (derived) | Can be derived without storing raw nationality |
| Geographic cluster | IP geolocation (derived) | Aggregate to city/metro level only |
| Account age cohort | Account creation date | Low sensitivity |
| Transaction pattern cluster | Behavioral clustering (derived) | No PII; derived feature |
| Language preference | App settings | Low sensitivity |

### 3.2 Minimum Sample Sizes

For statistically meaningful bias analysis:

| Analysis | Minimum per Group | Recommended per Group |
|---|---|---|
| Disparate impact ratio | 100 transactions | 1,000+ transactions |
| Equalized odds | 50 fraud cases per group | 200+ fraud cases per group |
| Demographic parity | 200 transactions | 1,000+ transactions |

### 3.3 Current Data Gaps

| Gap | Impact | Remediation Plan |
|---|---|---|
| PaySim synthetic data has no demographic attributes | Cannot perform disparate impact analysis | Audit will execute once production data with demographics is available |
| No real fraud labels for Trebanx transactions | Cannot validate true positive rates by group | Use PaySim labels as proxy; plan for label collection via investigation outcomes |
| Savings circle transactions not in PaySim | Circle-related bias cannot be assessed on training data | Generate synthetic circle transactions or evaluate post-deployment |

---

## 4. Audit Procedure

### 4.1 Pre-Audit Checklist

- [ ] Identify the model version and training data hash from MLflow
- [ ] Obtain demographic data for the evaluation dataset
- [ ] Verify minimum sample sizes per protected group
- [ ] Document the reference group and protected group definitions
- [ ] Confirm the scoring threshold used in production

### 4.2 Execution Steps

1. **Prepare Evaluation Dataset**
   - Join model predictions with demographic attributes
   - Segment by protected group
   - Verify label quality (confirmed fraud vs. suspected)

2. **Compute Fairness Metrics**
   - Calculate disparate impact ratio for each protected group
   - Calculate equalized odds (TPR and FPR parity)
   - Calculate demographic parity gap
   - Compute confidence intervals for all metrics

3. **Trebanx-Specific Checks**
   - Compare fraud flag rates: US-to-HT corridor vs. domestic transactions
   - Compare fraud flag rates: round-amount vs. non-round-amount transactions
   - Compare fraud flag rates: circle-related vs. non-circle transactions
   - Compare fraud flag rates by geographic cluster (Miami, NYC, Boston, other)

4. **Score Distribution Analysis**
   - Plot score distributions by protected group
   - Identify threshold effects (are certain groups clustered near the decision boundary?)
   - Analyze feature importance by group to identify proxy discrimination

5. **Document Findings**
   - Complete the audit results tables in Section 5
   - Record any bias detected and severity
   - Propose remediation if thresholds are exceeded

### 4.3 Post-Audit Actions

| Finding | Required Action | Timeline |
|---|---|---|
| All metrics within thresholds | Document results; schedule next audit | Next audit in 6 months |
| Marginal adverse impact (0.60-0.79 DIR) | Root cause analysis; feature review; consider mitigation | 30 days |
| Significant adverse impact (<0.60 DIR) | **Stop deployment**; retrain with bias mitigation; re-audit | Immediate |
| FPR disparity > 0.05 | Threshold adjustment or feature removal; re-audit | 30 days |

---

## 5. Audit Results Template

### 5.1 Audit Metadata

| Field | Value |
|---|---|
| Audit Date | _YYYY-MM-DD_ |
| Auditor | _Name and role_ |
| Model Name | _e.g., fraud-detector-v0.2_ |
| Model Version | _MLflow version number_ |
| Training Data Hash | _SHA-256 from MLflow_ |
| Evaluation Dataset | _Description and date range_ |
| Evaluation Dataset Size | _N transactions_ |
| Production Threshold | _e.g., 0.5_ |

### 5.2 Disparate Impact Results

| Protected Group | Reference Group | Protected Approval Rate | Reference Approval Rate | Disparate Impact Ratio | Pass/Fail |
|---|---|---|---|---|---|
| US-to-HT corridor | Domestic US | __%__ | __%__ | ____ | __ |
| Round-amount ($100/$200/$500) | Non-round amounts | __%__ | __%__ | ____ | __ |
| Circle-related transactions | Non-circle transactions | __%__ | __%__ | ____ | __ |
| New accounts (<90 days) | Established accounts | __%__ | __%__ | ____ | __ |
| _[Add groups as needed]_ | | | | | |

### 5.3 Equalized Odds Results

| Protected Group | Reference Group | TPR Protected | TPR Reference | TPR Diff | FPR Protected | FPR Reference | FPR Diff | Pass/Fail |
|---|---|---|---|---|---|---|---|---|
| US-to-HT corridor | Domestic US | __ | __ | __ | __ | __ | __ | __ |
| Round-amount | Non-round | __ | __ | __ | __ | __ | __ | __ |
| Circle-related | Non-circle | __ | __ | __ | __ | __ | __ | __ |
| _[Add groups]_ | | | | | | | | |

### 5.4 Demographic Parity Results

| Protected Group | Reference Group | Flag Rate Protected | Flag Rate Reference | Parity Gap | Pass/Fail |
|---|---|---|---|---|---|
| US-to-HT corridor | Domestic US | __ | __ | __ | __ |
| Round-amount | Non-round | __ | __ | __ | __ |
| Circle-related | Non-circle | __ | __ | __ | __ |
| _[Add groups]_ | | | | | |

### 5.5 Score Distribution Analysis

| Group | Mean Score | Median Score | P95 Score | % Above Threshold | Notes |
|---|---|---|---|---|---|
| Overall | __ | __ | __ | __ | Baseline |
| US-to-HT corridor | __ | __ | __ | __ | |
| Domestic US | __ | __ | __ | __ | |
| Round-amount | __ | __ | __ | __ | |
| Circle-related | __ | __ | __ | __ | |

### 5.6 Findings Summary

| Finding ID | Severity | Description | Affected Group | Metric | Value | Threshold | Remediation |
|---|---|---|---|---|---|---|---|
| _F-001_ | _Critical/High/Medium/Low_ | _Description_ | _Group_ | _Metric_ | _Value_ | _Threshold_ | _Action plan_ |

---

## 6. Remediation Procedures

If bias is detected above the defined thresholds, the following remediation
steps must be followed:

### 6.1 Immediate Actions (Significant Adverse Impact)

1. **Pause deployment** of the affected model version
2. **Notify BSA officer** and compliance team
3. **Revert to previous model version** if the bias was introduced by a model update
4. **Document the finding** with full audit results

### 6.2 Investigation and Mitigation

1. **Feature analysis:** Identify which features contribute most to disparate outcomes
   - Check for proxy variables (e.g., geographic features correlating with ethnicity)
   - Analyze feature importance by group using SHAP values
2. **Threshold adjustment:** Evaluate whether a different decision threshold
   reduces disparity without unacceptable loss in fraud detection
3. **Feature removal or transformation:**
   - Remove features that serve primarily as demographic proxies
   - Apply fairness-aware feature engineering (e.g., within-group normalization)
4. **Retraining with constraints:**
   - Apply in-processing bias mitigation (e.g., adversarial debiasing, fairness constraints)
   - Use reweighting or resampling to balance representation
5. **Post-processing calibration:**
   - Apply group-specific threshold calibration
   - Ensure calibrated probabilities are equally reliable across groups

### 6.3 Re-Audit

After remediation:

1. Retrain the model with the mitigation applied
2. Re-run the full bias audit on the new model version
3. Confirm all metrics are within thresholds
4. Obtain BSA officer sign-off before re-deploying

---

## 7. Audit Schedule

| Model | Audit Frequency | Next Scheduled Audit | Notes |
|---|---|---|---|
| fraud-detector-v0.2 | Every model retrain + semi-annually | When real demographic data is available | Critical priority |
| Compliance Risk Scorer v1 | Semi-annually | When real demographic data is available | High priority |
| Behavioral Anomaly Scorer v1 | Semi-annually | When real demographic data is available | High priority |
| Circle Health Scorer v1 | Annually | When real demographic data is available | Medium priority |

**Trigger-based audits:** An unscheduled bias audit must be conducted when:
- A new model version is trained on materially different data
- User complaints suggest disparate treatment
- Regulatory examination requires it
- The user base demographic composition changes significantly
