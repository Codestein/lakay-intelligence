# ADR 001: Event Schema Design for Trebanx-Lakay Integration

## Status
Accepted

## Context
Lakay Intelligence needs to consume events from the Trebanx platform for real-time fraud detection, behavioral analysis, circle health scoring, and compliance monitoring. We need a schema format for defining event contracts between the two systems.

## Decisions

### 1. JSON Schema Draft 2020-12 over Protobuf

We chose JSON Schema for event definitions because:
- **Human readability**: JSON schemas are easily readable and writable without specialized tooling
- **Ecosystem maturity**: Extensive library support in Python (`jsonschema`), JavaScript, Go, and other languages
- **Easier iteration**: During early development, schemas change frequently; JSON Schema allows rapid iteration without recompilation
- **Validation tooling**: JSON Schema validators can be embedded directly in consumers and generators

Trade-off: Protobuf offers better performance for serialization/deserialization and stronger type safety. We may migrate to Protobuf in later phases when schemas stabilize.

### 2. Decimal-as-string for monetary amounts

All monetary values use string representation (e.g., `"100.00"`) with a regex pattern `^\d+\.\d{2}$`:
- **Precision**: Avoids IEEE 754 floating-point representation errors
- **Safety**: JSON has no native decimal type; floats like `0.1 + 0.2` produce `0.30000000000000004`
- **Interoperability**: String representation is unambiguous across all languages and JSON parsers
- **Conversion**: Python consumers convert to `decimal.Decimal` for safe arithmetic

### 3. Standard event envelope structure

Every event uses the same envelope:
```json
{
  "event_id": "uuid-v4",
  "event_type": "event-name",
  "event_version": "1.0",
  "timestamp": "ISO 8601 with timezone",
  "source_service": "service-name",
  "correlation_id": "uuid-v4",
  "payload": { }
}
```

Rationale:
- **event_id**: Globally unique identifier for idempotency and deduplication
- **event_type**: Enables routing to correct consumers/handlers
- **event_version**: Supports schema evolution without breaking consumers
- **timestamp**: UTC with timezone for unambiguous time ordering
- **source_service**: Traceability to the originating service
- **correlation_id**: Enables distributed tracing of requests across service boundaries
- **payload**: Event-specific data, keeping the envelope clean

### 4. Separate schemas per event type

Each event type has its own JSON Schema file rather than using a single polymorphic schema:
- **Independent evolution**: Each event type can evolve without affecting others
- **Clear ownership**: Easy to identify which schema governs which event
- **Tooling compatibility**: Standard JSON Schema validators work out of the box
- **Documentation**: Each file serves as self-documenting contract

## Consequences

### Positive
- Fast development iteration during early phases
- Easy onboarding for new developers
- Strong validation guarantees in generators and consumers
- Clear contracts between Trebanx and Lakay teams

### Negative
- No compile-time type safety (mitigated by comprehensive tests)
- JSON serialization is less efficient than binary formats (acceptable at current scale)
- Schema duplication for shared structures like `geo_location` (mitigated by convention)
