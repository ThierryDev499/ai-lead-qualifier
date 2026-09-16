# Verification - 2026-09-16

- Five automated tests passed: scoring/filters/history, webhook authentication and replay handling, CRM simulator upsert, validation/model errors, and contact-field exclusion from prompts.
- Live `llama3.2:3b` qualification of bundled fictional leads produced scores 83 (`quente`), 50 (`morno`) and 5 (`frio`). These are observed outputs, not fixed application values.
- The first prompt produced unsupported price assumptions. The rubric was revised to score declared evidence and explicitly avoid affordability judgments. Earlier output remains in audit history rather than being hidden.
- Real local CRM simulation was triggered from the UI; it returned a stable demo ID and made no external request.
- Desktop 1366x900 and mobile 390x844 inspected, without page-level horizontal overflow or browser console errors/warnings.
- `pip-audit` found no known vulnerabilities in the locked dependency set.
- Docker files are included; local container execution was not verified while Docker Engine was unavailable.

The model's prose can still be imprecise. Scores are not calibrated conversion probabilities, and outreach remains a suggestion for human review.
