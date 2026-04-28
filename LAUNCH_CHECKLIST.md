# Launch Checklist

> Items in the codebase that depend on the **public launch date** and must be
> re-visited when that date is confirmed. The current placeholder is **2026-07-02**.
> Search globally for `2026-07-02` to find every occurrence.

---

## 1. Database

### `supabase/migrations/20260419010000_badges.sql`
- `auto_award_early_adopter()` uses hardcoded cutoff `2026-07-02T00:00:00Z` for the
  `early_adopter` badge. When the actual launch date is confirmed:
  1. Update the `v_cutoff` constant in the function body (`create or replace function ...`).
  2. Re-run the backfill block against any users who already signed up between now and the new cutoff.
  3. If cutoff is extended, also consider retiring or renaming the badge so future users don't
     get confused ("Early Adopter" means pre-launch, not just pre-July).

### `supabase/migrations/20260419000000_rate_limits_and_installations.sql`
- No launch-date dependency, but if you switch from BETA rate limits (120 req/min) to
  production limits, adjust the defaults in `check_rate_limit()`.

---

## 2. Backend

### `server/routes/upgrade.py`
- **Pro offer model (updated 2026-04-20):** 3-month redemption window grants
  12 months of Pro. Controlled by three constants:
  - `PRO_DURATION_DAYS = 365` (12 months granted per redemption)
  - `REDEMPTION_WINDOW_DAYS = 90` (3 months to redeem)
  - `BETA_START = datetime(2026, 5, 6, ...)` — **UPDATE this to the real public
    launch date** when confirmed. All other dates derive from it.
- Paid Pro pricing activates at least 3 months AFTER
  `BETA_START + REDEMPTION_WINDOW_DAYS`. Put billing system development
  behind that date.

### Telemetry consent wording (`packages/core/services/telemetry.py`)
- References to "beta" in `track_consent_change` response messages should be
  revisited when the product is GA.

---

## 3. Frontend

### `web/src/components/profile/UserProfile.tsx`
- `EARLY_ADOPTER_CUTOFF` constant — keep in sync with the DB function above, or
  remove the client-side check entirely and trust the server-issued badges (preferred
  long-term; the client computation is redundant once badges live in the DB).

### `web/src/components/upgrade/ProUpgradeCard.tsx`
- Copy aligned with redemption model ("3-month window to redeem 12 months of Pro",
  button "Redeem 12 months of Pro"). Update when pricing is finalized post-window.

---

## 4. Legal / landing

### `azelia-website/astro-landing/src/pages/terms.astro`
- Section 5 "Pro — beta redemption program" describes the 3-month redemption
  window + 12 months of Pro + telemetry consent. Update wording when beta ends
  and paid pricing activates.

### `azelia-website/astro-landing/src/pages/privacy.astro`
- "Vigente desde abril de 2026" — update the effective date if the policy changes
  materially at launch.

---

## 5. README / repo

### `README.md`
- "Beta" language throughout. Change to stable version references.
- Badges / shields section: add "Stable" or version tag when applicable.

---

## 6. Communications

- **Email campaign** to all `auth.users` with `created_at < actual_launch_date`
  — they get the `early_adopter` + `beta_pro` badge confirmations and
  "thanks for testing" messaging.
- Update the Pro offer wording in `ProUpgradeCard.tsx` and Show HN post.

---

## Actions when launch date is final

1. Search repo for `2026-07-02` — replace with final date.
2. Re-run the Supabase migration touching `auto_award_early_adopter()`.
3. Review this file and tick off items.
4. Delete this file or mark it "archived" once everything is migrated.

---

## 7. Language — P0 pre-launch (Added 2026-04-19)

The product and all user-facing copy must ship in **English only** for Show HN.
Current state is a ES/EN mix that undermines credibility.

### Frontend strings to translate (`web/src/`)

- `components/onboarding/OnboardingWizard.tsx` — most step labels and CTAs are in Spanish.
- `components/upgrade/ProUpgradeCard.tsx` — "El trueque", "Activar Pro (3 meses)", telemetry checkbox description.
- `components/profile/UserProfile.tsx` — "Insignias", "Hasta {date}", "Eliminando…", "Borra tu cuenta…" prompt, toast strings in handleDeleteAccount.
- `components/auth/LoginForm.tsx` — terms-accepted toast + signup button fallback strings.
- `components/workflow/DashboardController.tsx` — small bits like "Or upload manually" are English already; sweep for any missed.

### Backend response messages (`server/routes/`)

- `upgrade.py::activate_pro` returns `"¡Pro activado! Tienes 3 meses de acceso completo al IC Cascade."` — switch to English equivalent.
- `auth.py::mark_onboarding_complete` error details are mixed; make them English-first.
- `telemetry_routes.py` consent response message is Spanish.

### Landing pages (`azelia-website/astro-landing/src/`)

- `pages/privacy.astro` — **fully Spanish** (181 lines). Translate to English as primary; keep Spanish as a later `/privacy/es` if needed.
- `pages/terms.astro` — **fully Spanish** (162 lines). Same treatment.
- `pages/marketplace.astro` — fully Spanish, recently created. Translate.
- `pages/index.astro` — marketplace CTA block added in same session is Spanish. Translate.
- `components/Navbar.astro` — "Soon" badge and links are fine; verify no leftover ES.

### Sweep command

```bash
# inside each repo
grep -rEn "á|é|í|ó|ú|ñ|¿|¡|ó|Á|É|Í|Ó|Ú|Ñ" src/ --include='*.tsx' --include='*.astro' --include='*.py' --include='*.md'
```

### Recommended approach

1. Single-pass manual translation for all user-visible strings in one PR (no i18n scaffold yet).
2. Add `react-i18next` scaffold as a follow-up PR once English is stable.
3. Terms/Privacy in Spanish kept as a copy at `/privacy/es`, `/terms/es` for LATAM users later.
