# Security Policy

## Reporting a vulnerability

If you find a security issue, **please do not open a public GitHub issue**. Instead, email:

**`security@azelia.ai`** (or `hola@azelia.ai` if the security address is not live yet)

Include:
- A description of the vulnerability and what it affects.
- Steps to reproduce (minimal proof of concept is fine).
- Your assessment of severity and any potential impact.
- Optional: your name / handle for credit in the changelog.

We aim to acknowledge reports within **72 hours** and ship a fix for P0 issues within **7 days**. Lower severity issues are addressed on a rolling basis.

---

## Scope

### In scope

- `azelia-clips` codebase (this repository): pipeline, server, web client, CLI.
- Default Azelia-hosted endpoints that the client talks to by default (auth, IC Cascade, telemetry ingestion).
- Authentication flows: Supabase JWT handling, OAuth token storage (YouTube), session management.
- Data handling: how user content (transcripts, clips, API keys) is stored and transmitted.

### Out of scope

- Third-party services we integrate with (Supabase, Anthropic, OpenAI, YouTube) — report directly to them.
- Self-modified forks — if you changed the auth layer and broke it, that's on you.
- Social engineering or physical attacks.

---

## Severity guide (our internal tiers)

| Tier | Examples | Response SLA |
|------|----------|--------------|
| P0 | Authenticated user can access another user's data. Secrets leak. RCE. | 72h to patch, 7 days to release |
| P1 | Rate limit bypass, TOTP bypass, broken access control on low-value endpoint. | 2 weeks |
| P2 | Information disclosure of non-sensitive data. CSRF on non-destructive endpoint. | 4 weeks |
| P3 | Best-practice deviations, hardening suggestions. | Next minor release |

---

## Coordinated disclosure

If you report a valid issue, we:
1. Acknowledge within 72h.
2. Keep you in the loop while we patch.
3. Agree on a disclosure date (usually 7-30 days after the fix is live).
4. Credit you in the release notes (unless you prefer anonymity).

We do **not** operate a paid bug bounty during beta. If the issue is material, we'll consider a case-by-case reward.

---

## Known security posture

- **Authentication**: Supabase JWT, verified server-side on every authenticated endpoint.
- **OAuth tokens (YouTube)**: encrypted at rest with Fernet, stored in a user-isolated table.
- **RLS**: Supabase Row-Level Security enforced on `profiles`, `user_connections`, and all user-scoped tables.
- **Secrets**: API keys live in `.env` (not committed); the `AZELIA_ENCRYPTION_KEY` is required for token encryption at rest.
- **Audit trail**: telemetry consent changes, onboarding completion, and tier upgrades are timestamped in the `profiles` row.

Any deviation from the above — e.g. an endpoint that doesn't verify the JWT, or a write path that bypasses RLS — is a bug. Report it.

---

Thank you for helping keep Azelia safe.
