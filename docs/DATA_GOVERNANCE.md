# Data governance (M0.1)

## Classification
- Synthetic: invented solely for tests, clearly labelled; never publish as passenger information.
- Authorized: real data whose permitted source, purpose, access and redistribution scope are independently documented.
- Unverified: any other or uncertain data; deny ingestion and publication by default.

A caller's label is not proof of authorization. M0.1 accepts only the exact development fixture metadata schema and values; copies of the fixture are not evidence of authorization. No actual transit records are loaded. No real-data connector exists.

## Evidence required before real data
Record the agency, named authorized contact or role, approval reference, allowed endpoints/data, permitted uses, recipients, duration, refresh limits, attribution, revocation procedure and separate publication scope. Store sensitive evidence privately. Do not put correspondence, tokens, restricted source records or personal data in the public repository.

## Release gate
Future production release requires independently checked scope, valid source evidence, a feed hash tied to the validation report, coverage/freshness checks, approval to distribute, and platform acceptance for public availability. Revocation and expiry block subsequent release. M0.1 denies all publication regardless of classification or validation claims. No production transport access or hosting exists.

## License and operations
Apache-2.0 covers BOT code only. Third-party data rights are independent. No secrets in git; use private local storage or approved secret management. Maintain a future incident and correction channel, audit trail, and handover plan.
