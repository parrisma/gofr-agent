# Hub Observability Strategy

## Symptom

The real server can answer some hub-backed questions, but startup logs do not make it obvious whether the built-in results hub is enabled, which services successfully registered hub support, or whether a later tool failure is a hub-registration problem, a descriptor misuse problem, or some other downstream error.

## Hypothesized Root Cause

The registry already tracks service-level hub capabilities and registration errors, but startup logging only reports a generic "Registered service" message. Tool execution logging is also too narrow: auth denials are visible, but other non-fatal downstream failures are still returned in-band to the model/UI without a structured server log.

## Assumptions And Validation

- `ServiceRegistry` knows whether each service supports the results hub and whether registration failed.
- `start-real-server.sh` does not currently surface hub configuration in its banner.
- Downstream fixture analytics tools raise `Results hub is not configured` only when they are called with `bars_ref` and attempt hub dereferencing.
- The same complex prompts succeed via CLI, which makes a caller/UI flow issue plausible even when the backend is healthy.

## Diagnostics Order

1. Log startup hub configuration in the real-server launcher banner.
2. Log per-service startup capability details from the registry, including hub support and registration errors.
3. Log an aggregated startup summary showing whether the hub is enabled, whether the hub URL is configured, and how many services registered hub capabilities successfully.
4. Extend downstream tool error logging beyond auth denials so non-fatal hub, descriptor, and argument failures are also visible in the server logs.
5. Preserve structured tool error payloads so the UI can still inspect exact error details.