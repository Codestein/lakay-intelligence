# Synthetic Data Generators

Phase 10 -- Task 10.5: Synthetic data generator documentation.

Lakay Intelligence ships four synthetic data generators that produce realistic event
streams for development, testing, load testing, and fraud-scenario validation.
All generators share a common base class (`generators/base.py`) that provides
deterministic UUID generation, seeded RNG, event envelope formatting, and
weighted-choice helpers.

---

## CLI Usage

All generators are invoked through the unified CLI entry point:

```bash
python -m generators <generator> --config <config_path> [--seed N] [--count N] [--output stdout|file|kafka] [--output-file path]
```

### Examples

```bash
python -m generators circle --config generators/configs/default_circle.yaml --seed 42 --count 100
python -m generators transaction --config generators/configs/default_transaction.yaml --count 10000
python -m generators session --config generators/configs/default_session.yaml --count 5000
python -m generators remittance --config generators/configs/default_remittance.yaml --count 5000
```

### Arguments

| Argument        | Type   | Default  | Description                                       |
|-----------------|--------|----------|---------------------------------------------------|
| `generator`     | choice | required | One of: `circle`, `transaction`, `session`, `remittance` |
| `--config`      | str    | required | Path to YAML configuration file                   |
| `--seed`        | int    | `42`     | Random seed for reproducibility                   |
| `--count`       | int    | `100`    | Number of primary entities to generate             |
| `--output`      | choice | `stdout` | Output destination: `stdout`, `file`, or `kafka`   |
| `--output-file` | str    | `None`   | File path for `--output file` (defaults to `output/<generator>_events.jsonl`) |

### Configuration Files

| Config File                  | Purpose                                      |
|------------------------------|----------------------------------------------|
| `default_circle.yaml`        | Standard circle lifecycle parameters         |
| `default_transaction.yaml`   | Standard transaction generation parameters   |
| `default_session.yaml`       | Standard session behavior parameters         |
| `default_remittance.yaml`    | Standard US-Haiti remittance parameters      |
| `fraud_scenarios.yaml`       | Elevated fraud injection rates for all generators |
| `stress_test.yaml`           | High-volume parameters for load testing      |

---

## Event Envelope

Every event produced by every generator uses the same envelope structure:

```json
{
  "event_id": "<uuid>",
  "event_type": "<event-type>",
  "event_version": "1.0",
  "timestamp": "<ISO-8601>",
  "source_service": "<service-name>",
  "correlation_id": "<uuid>",
  "payload": { ... }
}
```

---

## 1. Circle Generator

**Class:** `CircleGenerator` (`generators/circle_generator.py`)

Simulates complete sou-sou circle lifecycles: creation, member joins, contribution
cycles with payments (on-time, late, missed), payouts, member drops, circle failures,
collusion patterns, and circle completion.

### Events Produced

| Event Type                     | Source Service       | Description                                  |
|--------------------------------|----------------------|----------------------------------------------|
| `circle-created`               | `circle-service`     | Circle initialization with organizer, frequency, and contribution amount |
| `circle-member-joined`         | `circle-service`     | Member join with position and verification status |
| `circle-contribution-received` | `circle-service`     | On-time or late contribution payment         |
| `circle-contribution-missed`   | `circle-service`     | Member missed a contribution                 |
| `circle-payout-executed`       | `circle-service`     | Payout to the cycle recipient                |
| `circle-member-dropped`        | `circle-service`     | Member dropped (voluntary, missed payments, or removed) |
| `circle-failed`                | `circle-service`     | Circle terminated early (insufficient members or excessive defaults) |
| `circle-completed`             | `circle-service`     | Circle completed all cycles                  |
| `transaction-initiated`        | `transaction-service` | Transaction created for each contribution    |
| `transaction-completed`        | `transaction-service` | Transaction settlement confirmation          |

### Key Configurable Parameters

| Parameter               | Type          | Default        | Description                                  |
|-------------------------|---------------|----------------|----------------------------------------------|
| `member_range`          | `[int, int]`  | `[5, 12]`      | Min/max members per circle                   |
| `contribution_range`    | `[float, float]` | `[50.0, 300.0]` | Min/max contribution amount (USD)          |
| `frequency_weights`     | `dict`        | `{weekly: 0.2, biweekly: 0.3, monthly: 0.5}` | Weighted distribution of cycle frequency |
| `late_payment_rate`     | `float`       | `0.10`         | Probability a payment is late                |
| `late_payment_days_mean`| `float`       | `3`            | Mean days late (Gaussian)                    |
| `late_payment_days_std` | `float`       | `2`            | Std dev of days late                         |
| `miss_payment_rate`     | `float`       | `0.05`         | Probability a payment is missed entirely     |
| `member_drop_rate`      | `float`       | `0.03`         | Probability a member drops per cycle         |
| `circle_failure_rate`   | `float`       | `0.05`         | Probability a circle fails before completion |
| `collusion_rate`        | `float`       | `0.02`         | Probability of collusion (first recipient drops after payout) |
| `fraud_injection_rate`  | `float`       | `0.02`         | General fraud injection rate                 |

### Example Output Event

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "event_type": "circle-created",
  "event_version": "1.0",
  "timestamp": "2026-01-15T10:30:00+00:00",
  "source_service": "circle-service",
  "correlation_id": "660e8400-e29b-41d4-a716-446655440001",
  "payload": {
    "circle_id": "770e8400-e29b-41d4-a716-446655440002",
    "organizer_id": "880e8400-e29b-41d4-a716-446655440003",
    "name": "Lakay Savings Group",
    "contribution_amount": "100.00",
    "currency": "USD",
    "frequency": "monthly",
    "max_members": 10,
    "rotation_order": "sequential",
    "start_date": "2026-02-01",
    "status": "pending"
  }
}
```

### Extending with New Patterns

1. **New event types:** Add a new `self._envelope(...)` call within `_generate_circle()`.
   Follow the existing pattern of constructing a payload dict and passing it through
   the envelope helper.

2. **New fraud patterns:** Add a new config parameter (e.g., `new_fraud_rate`),
   read it via `config.get("new_fraud_rate", 0.0)`, and inject the pattern
   conditionally based on `random.random() < rate`. The collusion pattern in the
   existing code is a good model to follow.

3. **New lifecycle stages:** Insert additional event emissions at the appropriate point
   in the cycle loop. Keep events chronologically ordered; the generator sorts all
   events by timestamp before returning.

---

## 2. Transaction Generator

**Class:** `TransactionGenerator` (`generators/transaction_generator.py`)

Generates realistic transaction event streams across multiple transaction types
with configurable fraud injection including structuring patterns and velocity
anomalies.

### Events Produced

| Event Type              | Source Service       | Description                                  |
|-------------------------|----------------------|----------------------------------------------|
| `transaction-initiated` | `transaction-service` | Transaction creation with amount, type, geo, device |
| `transaction-completed` | `transaction-service` | Successful settlement with fees and net amount |
| `transaction-failed`    | `transaction-service` | Failed transaction with error code and retry eligibility |
| `transaction-flagged`   | `transaction-service` | Suspicious transaction flagged with risk score and action taken |

### Key Configurable Parameters

| Parameter                    | Type    | Default  | Description                                         |
|------------------------------|---------|----------|-----------------------------------------------------|
| `num_users`                  | `int`   | `500`    | Size of the synthetic user pool                     |
| `time_span_days`             | `int`   | `90`     | Time range for generated events                     |
| `type_weights`               | `dict`  | see below | Weighted distribution of transaction types         |
| `amount_distribution.log_normal_mean` | `float` | `4.5` | Log-normal mean for amount distribution       |
| `amount_distribution.log_normal_std`  | `float` | `1.2` | Log-normal std for amount distribution        |
| `fraud_injection_rate`       | `float` | `0.03`  | Rate of general fraud-flagged transactions          |
| `structuring_injection_rate` | `float` | `0.01`  | Rate of structuring-pattern amounts ($2,800-$2,999 or $9,500-$9,999) |
| `velocity_anomaly_rate`      | `float` | `0.02`  | Rate of velocity spike injection (8-15 rapid transactions) |

Default transaction type weights:

```yaml
type_weights:
  circle_contribution: 0.35
  circle_payout: 0.15
  remittance: 0.30
  fee: 0.15
  refund: 0.05
```

### Example Output Event

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440010",
  "event_type": "transaction-initiated",
  "event_version": "1.0",
  "timestamp": "2026-01-15T14:00:00+00:00",
  "source_service": "transaction-service",
  "correlation_id": "660e8400-e29b-41d4-a716-446655440011",
  "payload": {
    "transaction_id": "770e8400-e29b-41d4-a716-446655440012",
    "user_id": "880e8400-e29b-41d4-a716-446655440003",
    "type": "circle_contribution",
    "amount": "100.00",
    "currency": "USD",
    "source": { "type": "stripe", "identifier": "pm_test_123" },
    "destination": { "type": "balance", "identifier": "circle_pool_001" },
    "initiated_at": "2026-01-15T14:00:00+00:00",
    "ip_address": "10.0.1.50",
    "device_id": "device_abc123",
    "geo_location": {
      "latitude": 42.3601,
      "longitude": -71.0589,
      "country": "US",
      "city": "Boston"
    }
  }
}
```

### Extending with New Patterns

1. **New transaction types:** Add the type to `type_weights` in the config. No code
   changes required -- the generator uses `self._weighted_choice(type_weights)` to
   select types dynamically.

2. **New fraud injection patterns:** Add a new injection rate config parameter
   and a conditional block similar to the existing `structuring_injection_rate`
   or `velocity_anomaly_rate` blocks. Place the new block before the standard
   event generation to allow it to modify or replace the transaction.

3. **New transaction states:** Add new event emissions in `_make_transaction_events()`
   to model additional lifecycle states (e.g., `transaction-refunded`,
   `transaction-disputed`).

---

## 3. Session Generator

**Class:** `SessionGenerator` (`generators/session_generator.py`)

Generates user session event streams including login attempts, session
lifecycle, user actions, and anomaly injection for account takeover and
impossible travel detection.

### Events Produced

| Event Type              | Source Service  | Description                                          |
|-------------------------|-----------------|------------------------------------------------------|
| `login-attempt`         | `user-service`  | Login attempt with device, IP, geo, and auth method  |
| `login-success`         | `user-service`  | Successful authentication with session ID            |
| `login-failed`          | `user-service`  | Failed login with failure reason and consecutive count |
| `session-started`       | `user-service`  | Session initialization with device and location      |
| `user-action-performed` | `user-service`  | Individual user action within a session              |
| `session-ended`         | `user-service`  | Session termination with duration and action count   |

### Key Configurable Parameters

| Parameter                              | Type    | Default  | Description                                       |
|----------------------------------------|---------|----------|---------------------------------------------------|
| `num_users`                            | `int`   | `500`    | Size of the synthetic user pool                   |
| `time_span_days`                       | `int`   | `90`     | Time range for generated events                   |
| `session_duration_distribution.log_normal_mean` | `float` | `6.0` | Log-normal mean for session duration (seconds) |
| `session_duration_distribution.log_normal_std`  | `float` | `1.0` | Log-normal std for session duration            |
| `actions_per_session_distribution.log_normal_mean` | `float` | `2.0` | Log-normal mean for actions per session     |
| `actions_per_session_distribution.log_normal_std`  | `float` | `0.8` | Log-normal std for actions per session      |
| `anomaly_injection_rate`               | `float` | `0.03`  | Rate of anomaly injection (impossible travel uses 30% of this) |
| `account_takeover_injection_rate`      | `float` | `0.01`  | Rate of ATO pattern injection (new device, IP, location) |
| `device_diversity`                     | `int`   | `2`     | Device diversity parameter                        |
| `location_diversity`                   | `int`   | `3`     | Location diversity parameter                      |

Action types generated:

- `page_view`, `button_click`, `form_submit`, `circle_browse`, `circle_join_request`
- `contribution_initiate`, `remittance_initiate`, `settings_change`, `support_contact`

Device types: `ios`, `android`, `web_desktop`, `web_mobile`

ATO-injected sessions bias actions toward: `remittance_initiate`, `settings_change`,
`form_submit` (high-value/sensitive actions).

### Example Output Event (login-attempt)

```json
{
  "event_id": "aae94c00-1234-4abc-b567-def012345678",
  "event_type": "login-attempt",
  "event_version": "1.0",
  "timestamp": "2026-01-20T09:15:00+00:00",
  "source_service": "user-service",
  "correlation_id": "bbe94c00-2345-4bcd-c678-ef0123456789",
  "payload": {
    "user_id": "880e8400-e29b-41d4-a716-446655440003",
    "attempt_id": "cce94c00-3456-4cde-d789-f01234567890",
    "ip_address": "42.128.55.201",
    "device_id": "device_a1b2c3d4e5f67890",
    "device_type": "ios",
    "user_agent": "Trebanx/1.0 iOS/17.4",
    "geo_location": {
      "latitude": 42.3601,
      "longitude": -71.0589,
      "country": "US",
      "city": "Boston",
      "state": "MA"
    },
    "attempted_at": "2026-01-20T09:15:00+00:00",
    "auth_method": "biometric"
  }
}
```

### Extending with New Patterns

1. **New action types:** Add entries to the `ACTION_TYPES` list at the module level.
   They will be automatically sampled during session action generation.

2. **New anomaly patterns:** Add a new injection rate config parameter, check it in
   the main `generate()` loop, and modify the user or session parameters accordingly.
   The ATO pattern (lines 79-87) is a good model: it copies the user dict and
   replaces device/IP/location fields.

3. **New device types:** Add entries to `DEVICE_TYPES` and `USER_AGENTS` dicts at
   the module level.

---

## 4. Remittance Generator

**Class:** `RemittanceGenerator` (`generators/remittance_generator.py`)

Generates US-to-Haiti remittance flows with realistic exchange rate fluctuations,
seasonal patterns, delivery method distribution, and multi-stage processing
pipelines.

### Events Produced

| Event Type               | Source Service       | Description                                         |
|--------------------------|----------------------|-----------------------------------------------------|
| `exchange-rate-updated`  | `remittance-service` | Daily USD/HTG exchange rate update                  |
| `remittance-initiated`   | `remittance-service` | Remittance creation with sender, recipient, amounts, delivery method |
| `remittance-processing`  | `remittance-service` | Processing stage updates (compliance_check, funds_captured, partner_submitted, in_transit) |
| `remittance-completed`   | `remittance-service` | Successful delivery with actual exchange rate and confirmation |
| `remittance-failed`      | `remittance-service` | Failed remittance with reason and refund status     |

### Key Configurable Parameters

| Parameter                             | Type      | Default  | Description                                    |
|---------------------------------------|-----------|----------|------------------------------------------------|
| `num_senders`                         | `int`     | `300`    | Size of the sender pool                        |
| `time_span_days`                      | `int`     | `90`     | Time range for generated events                |
| `exchange_rate_base`                  | `float`   | `132.50` | Base USD/HTG exchange rate                     |
| `exchange_rate_volatility`            | `float`   | `0.02`   | Daily rate volatility (fraction)               |
| `send_amount_distribution.common_amounts` | `list` | `[50, 100, 200, 300, 500]` | Common remittance amounts       |
| `send_amount_distribution.common_amount_probability` | `float` | `0.6` | Probability of using a common amount |
| `send_amount_distribution.random_mean`| `float`   | `200`    | Mean for random amount Gaussian                |
| `send_amount_distribution.random_std` | `float`   | `150`    | Std dev for random amount Gaussian             |
| `delivery_method_weights`             | `dict`    | see below | Weighted distribution of delivery methods     |
| `success_rate`                        | `float`   | `0.95`   | Remittance completion success rate             |
| `processing_time_hours_mean`          | `float`   | `24`     | Mean processing time in hours                  |
| `seasonal_patterns`                   | `bool`    | `true`   | Enable seasonal volume adjustments             |
| `fraud_injection_rate`                | `float`   | `0.02`   | Fraud injection rate                           |

Default delivery method weights:

```yaml
delivery_method_weights:
  mobile_wallet: 0.45
  bank_deposit: 0.30
  cash_pickup_agent: 0.25
```

Seasonal multipliers (when `seasonal_patterns: true`):

| Period                    | Multiplier | Reason                              |
|---------------------------|------------|-------------------------------------|
| Dec 15 -- Jan 7           | 2.5x       | Holiday season / Haitian diaspora   |
| Feb 10 -- Feb 20          | 1.8x       | Carnival season                     |
| Apr 1 -- Apr 15           | 1.5x       | Easter / family support             |
| September                 | 1.3x       | Back-to-school                      |
| June -- July              | 0.8x       | Lower volume summer                 |
| All other periods         | 1.0x       | Baseline                            |

### Example Output Event

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440020",
  "event_type": "remittance-initiated",
  "event_version": "1.0",
  "timestamp": "2026-01-15T16:00:00+00:00",
  "source_service": "remittance-service",
  "correlation_id": "660e8400-e29b-41d4-a716-446655440021",
  "payload": {
    "remittance_id": "770e8400-e29b-41d4-a716-446655440022",
    "sender_id": "880e8400-e29b-41d4-a716-446655440003",
    "recipient_name": "Marie Jean-Baptiste",
    "recipient_phone": "+50934567890",
    "recipient_country": "HT",
    "send_amount": "200.00",
    "send_currency": "USD",
    "receive_amount": "26500.00",
    "receive_currency": "HTG",
    "exchange_rate": "132.50",
    "delivery_method": "mobile_wallet",
    "initiated_at": "2026-01-15T16:00:00+00:00",
    "fee_amount": "4.99"
  }
}
```

### Extending with New Patterns

1. **New corridors:** The generator is currently hardcoded for US-to-Haiti. To add
   a new corridor, parameterize the recipient country and location generation.
   Replace calls to `random_haiti_location()` with a corridor-aware factory.

2. **New delivery methods:** Add entries to the `delivery_method_weights` config.
   If the method requires extra payload fields (like `agent_id` for cash pickup),
   add a conditional block after the delivery method selection.

3. **New processing stages:** Modify the `stages` list in the generation loop to
   add or remove processing steps. Each stage emits a `remittance-processing` event.

4. **Custom exchange rate models:** Replace the random walk in the exchange rate
   generation loop with a more sophisticated model (e.g., mean-reverting, GARCH).

---

## Shared Infrastructure

### Base Generator (`generators/base.py`)

All generators extend `BaseGenerator`, which provides:

- **Deterministic seeding:** `random.seed(seed)` and `np.random.seed(seed)` ensure
  reproducible output across runs with the same seed.
- **UUID generation:** `_uuid()` produces deterministic UUIDs based on the seeded RNG.
- **Event envelope:** `_envelope(event_type, source_service, payload, ...)` wraps
  payloads in the standard event structure.
- **Decimal formatting:** `_decimal_str(value)` formats floats as 2-decimal strings.
- **Weighted choice:** `_weighted_choice(options)` selects from a dict of weighted options.
- **Random datetime:** `_random_datetime(start, end)` generates a random timestamp
  within a range.

### Utility Modules

| Module                          | Purpose                                         |
|---------------------------------|-------------------------------------------------|
| `generators/utils/distributions.py` | Log-normal sampling, weighted amounts, seasonal multipliers, IP/device ID generation |
| `generators/utils/geography.py`     | US and Haiti location pools, geo coordinate generation |
| `generators/utils/names.py`         | Synthetic name, email, and phone generation     |

### Output Handling

The CLI supports three output modes:

- **`stdout`** (default): One JSON event per line (JSONL format) to stdout.
- **`file`**: Write JSONL to the specified path (or `output/<generator>_events.jsonl`).
  Parent directories are created automatically.
- **`kafka`**: Placeholder -- not yet implemented. Exits with error message.
