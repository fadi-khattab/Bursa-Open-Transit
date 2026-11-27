# BOT-M2A — Canonical transit kernel (offline)

Baseline: public development commit d79692d. Scope: synthetic, single-timezone network; no real ingestion, publication, or GTFS serialization.

## Relations
Agency 1:N Route; Route 1:N Pattern; Pattern 1:N Trip; Calendar 1:N Trip.
Pattern is an ordered tuple of stop references. A trip's visit sequence must exactly match its pattern, including repeated stops. The visit's tuple position defines its occurrence, not the stop ID. IDs are unique within entity type and supplied by the synthetic caller; persistence and cross-snapshot identity reconciliation are future work.

## Time
ServiceTime stores nonnegative integral schedule seconds, without a 24-hour wrap. Service dates use ISO weekdays 1–7 and inclusive date intervals. Explicit dated exceptions override base rules, including additions outside the interval. All agencies in a network share a valid IANA timezone; absolute timestamps and DST conversion are out of scope.
Known and estimated visits require arrival/departure pairs. Unknown intermediate visits contain neither. Trip endpoints must be timed. Arrival <= departure and known/estimated values must be monotonic even across unknown visits. No interpolation, no fabricated time.

## Constraints and boundaries
Immutable typed entities; validated coordinate ranges and finite values; unique typed IDs; no dangling references; exact ordered visit matching. Synthetic namespace and metadata are development conventions, not proof of data origin or permission. The code accepts manually constructed objects and does not authenticate their contents. Known means caller-declared, not independently verified. The demo is fictional and not geographically representative of Bursa. No journey routing, transfer model, station hierarchy, shapes, fares, pickup/drop-off, frequency services, accessibility, source evidence records, coverage checks, persistent ID mapping or production validator in M2A. Calendar rules are representable but a calendar may have no operating days; production coverage is a separate gate. M2B should add these features as appropriate and test cross-snapshot identity, service coverage and provenance before M3.

Existing M0.1 CLI and version remain unchanged; its status reports the foundation, not the M2A implementation. Publication stays disabled. No external dependencies added.
