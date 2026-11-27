# Bursa Open Transit (BOT)

[ Türkçe ](README.tr.md) · [ English ](README.md)

**Independent volunteer initiative for public transport information in Bursa, Türkiye.**

Our goal is to make scheduled bus, tram and BursaRay information easier to find in Google Maps, using authorized GTFS Schedule data and, in a later phase, GTFS Realtime.

## Current status

**Development only — not a passenger journey planner or an official feed.** The software foundation is implemented; GTFS generation, production adapters, hosting and realtime integration are not implemented. Agency endorsement, authorized source data and platform acceptance are pending. BOT is not affiliated with or endorsed by BURULAŞ or Google.

## Proposed cooperation

1. Prefer an existing agency-authorized GTFS feed, if available.
2. Otherwise transform a supported periodic export (CSV, JSON or XML).
3. If appropriate, use a documented read-only API under agreed access and distribution terms.

Begin with an agency-selected pilot and validate both the feed and sample journeys before any official release. No passenger, card or payment data is required.

## Development

Python 3.12 or later. From the repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest
python -m bursa_transit
```

The CLI reports development-only mode and denies official publication. Tests exercise the foundation and synthetic fixture metadata, not real transport data or a production pipeline.

## Documentation

- [Project charter](docs/PROJECT_CHARTER.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Roadmap](docs/ROADMAP.md)
- [Data governance](docs/DATA_GOVERNANCE.md)
- [Public progress and next steps](docs/PUBLIC_STATUS.md)

## License and contributions

Apache-2.0 covers project code, not third-party data or correspondence. Contributions to documentation, offline synthetic tests and standards-based design are welcome. Do not submit private records, credentials, unauthorized datasets or third-party application source code. Report general project issues via GitHub Issues without including sensitive data.
