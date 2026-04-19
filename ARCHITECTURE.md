# Architecture

> What's open source, what's proprietary, and why.

Azelia Clips is **MIT licensed** — the entire client, backend, and multi-agent pipeline is in this repository and free to use, modify, and redistribute. This document exists to be transparent about what stays proprietary and why that line is drawn where it is.

---

## Open source (MIT, this repository)

Everything in `azelia-clips` under MIT:

- **Client** (`web/`) — Astro + React dashboard, onboarding wizard, review interface
- **Server** (`server/`) — FastAPI backend: routes, middleware, auth verification, job orchestration
- **Pipeline** (`packages/clips/`) — transcription, multi-agent curation (Finder → Critic → Ranker), reframing, subtitles
- **Core libraries** (`packages/core/`) — auth, crypto, config, services
- **CLI** — `azelia` command-line tool
- **E2E tests, infra scripts, migrations** — everything you need to run Azelia locally

If you want to fork it, rebrand it, ship it as your own product: the license allows that. No hidden traps, no "but actually" clauses.

---

## Proprietary (not in this repository)

These are infrastructure and data assets that live on Azelia's servers and are not part of the MIT-licensed code:

### 1. IC Cascade — the signals dataset

Aggregated signals derived from community telemetry: hook patterns, duration benchmarks, sentiment distributions, performance curves. Updated weekly from anonymous metrics contributed by opted-in Pro users.

This is the moat. The pipeline code can detect clips; the dataset is what makes them *ranked intelligently*. Without it, Azelia Clips is a capable curator. With it, it's calibrated against thousands of real podcast shorts that actually performed.

Any self-hosted installation can query read-only against the Azelia central API to get current IC Cascade rankings (subject to rate limits). Write access — contributing new signals — is gated behind Pro tier consent.

### 2. Ranker weights (trained models)

The Ranker agent uses a scoring model trained on the IC Cascade + retention data. The prompt skeleton is open source in this repo. The weights, training data, and training pipeline are not.

### 3. Central Supabase instance

Our hosted database powers authentication, billing, telemetry ingestion, Pro tier gating, and IC Cascade distribution. Default builds of the MIT code connect here. Rate-limited per `installation_id`. Subject to the [Terms of Service](https://azelia.ai/terms) separate from the MIT license of the client.

### 4. The "Azelia" name and brand

Trademark pending. The name, logo, and visual identity are not covered by MIT. A fork can reuse the code under any name — not "Azelia".

---

## Why this split

**MIT maximizes reach.** We want Azelia Clips to be the default multi-agent podcast clipper — the one developers read to learn, the one indie creators fork to customize, the one cited in research. That requires permissive licensing without caveats.

**The dataset and weights stay proprietary because they compound.** Every clip processed by the community that opts into telemetry makes the IC Cascade more accurate. That flywheel is what funds the infrastructure that keeps the MIT code maintained. If the dataset were MIT too, forks could match feature parity instantly — the incentive to invest in the pipeline would collapse.

**We're betting on distribution over protection.** We'd rather 10,000 installations running Azelia (connected to our IC Cascade, contributing telemetry) than 500 installations of a proprietary clone. MIT is what gets us to 10,000.

---

## For contributors

If you contribute code back to this repo, you sign a [Contributor License Agreement](./CLA.md) that gives Azelia broad rights to use, relicense, and distribute your contribution. This is standard for MIT projects that need future flexibility — see the CLA file for the exact terms.

---

## Questions

- **Can I use Azelia Clips to build a competing SaaS?** Yes, MIT allows it. You'll have to build your own IC Cascade dataset though — ours isn't included.
- **Can I self-host and not connect to your Supabase?** Technically yes if you modify `packages/core/config.py` to point elsewhere. Not officially supported and you lose IC Cascade + auth.
- **Can I use the "Azelia" name on my fork?** No — that's trademark, not license.
- **Will the IC Cascade ever be open?** Not planned. The models trained on it may be released as checkpoints after a lag.

Contact for anything else: `hola@azelia.ai`.
