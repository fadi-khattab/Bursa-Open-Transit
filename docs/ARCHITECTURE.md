# Architecture (M0.1)

## Pipeline (target, not implemented)
Authorized source or synthetic fixture -> source adapter -> normalized canonical transit model -> GTFS generation -> independent validation -> approved release -> consumer.

Separate source access, transformation, validation and release. Every future output should carry a provenance record with source identity, version/hash, observation time, transformation version, validation report and authorization scope.

## Components
- sources: adapter interfaces and provenance classification.
- models: canonical entities (agency, stop, route, trip, stop time, service calendar).
- normalization: stable identifier mapping, time/coordinate normalization, no silent data invention.
- gtfs: deterministic Schedule export.
- realtime: future feed linked to matching Schedule identifiers.
- validation: structural and semantic checks plus independent MobilityData validation.
- publishing: fail-closed release boundary; M0.1 implements no publisher.

## Design constraints
Use Europe/Istanbul for agency-local schedules; distinguish service-day time (including after-midnight GTFS times) from absolute timestamps. Keep stable IDs across refreshes. Keep synthetic and authorized data isolated. Reject missing provenance. No production credentials in code or repository. Future releases must be atomic, monitored, versioned and reversible. Failures must not replace a last known good feed with invalid data.

## M0.1 implemented scope
Package skeleton, explicit synthetic provenance, offline fixture loading, fail-closed publication decision, status CLI and tests. No external adapters, real transit model, GTFS generation or deployment yet.

## References
- https://gtfs.org/documentation/schedule/reference/
- https://gtfs.org/documentation/realtime/reference/
- https://gtfs-validator.mobilitydata.org/
- https://support.google.com/transitpartners/
