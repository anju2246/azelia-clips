# Privacy Policy

**Last Updated:** March 6, 2026

Azelia ("we," "our," or "us") operates the Azelia Clips software and related services. This Privacy Policy explains how we collect, use, and protect information when you use our software.

**Contact:** [legal@azelia.ai](mailto:legal@azelia.ai)

---

## 1. Information We Collect

### 1.1 Account Information
When you create an account, we collect:
- Email address
- Name (if provided)
- Authentication credentials (managed by Supabase)

If you sign in via Google or GitHub OAuth, we receive your public profile information from those services.

### 1.2 Onboarding Profile
During the setup wizard, we collect:
- Content niche (e.g., business, comedy, education)
- User role (solo creator, editor, agency, network producer)
- Primary goal (grow audience, save time, monetize)
- Podcast name and local directory path
- AI provider preferences and API keys (stored locally in `.env`, NOT sent to our servers)

### 1.3 YouTube Data (Optional)
If you connect your YouTube channel, we access:
- Channel name, ID, and subscriber count
- Video metadata (titles, view counts, publish dates)
- YouTube Analytics data (watch time, CTR, retention, impressions)

This data is stored **locally on your machine** in a SQLite database. It is never uploaded to our servers.

### 1.4 Local Data (Never Leaves Your Machine)
The following data is processed and stored exclusively on your local device:
- Video and audio files
- Transcripts and subtitles
- Generated clips
- AI curation results
- Application settings and preferences

**We do not have access to this data.**

### 1.5 Anonymized Telemetry (Opt-In with Consent)
During onboarding, you are asked to enable or disable anonymized usage telemetry. If you consent, we collect:
- Clip metadata: duration, style, hook type
- Performance metrics: processing times, pipeline success rates
- System information: software version, OS, hardware type
- Error diagnostics: crash logs and processing failures

**We do NOT collect:** video/audio content, transcripts, or any personally identifiable information through telemetry.

**You can change your preference at any time** by setting `CELIA_TELEMETRY_OPT_OUT=true` in your environment or toggling the setting in the dashboard.

## 2. How We Use Your Information

| Purpose | Data Used | Legal Basis |
|---------|-----------|-------------|
| Account management | Email, name | Contract performance |
| Product improvement | Anonymized telemetry | Explicit consent (onboarding) |
| Collective Intelligence | Aggregated metrics | Explicit consent (onboarding) |
| Error diagnosis | Crash logs | Explicit consent (onboarding) |
| Industry research & commercial insights | Anonymized, aggregated data | Legitimate interest |

## 3. Data Sharing

We **do not sell** your personal information (email, name, profile data).

We **may sell, license, or share** aggregated, anonymized insights derived from telemetry data with third parties. This data cannot be traced back to any individual user.

We may also share data with:
- **Service providers** (Supabase for authentication) who process data on our behalf under strict confidentiality agreements
- **Legal requirements:** when required by law or to protect our rights

## 4. Data Storage & Security

- **Authentication data:** stored in Supabase (US/EU data centers) with encryption at rest and in transit
- **Local data:** stored on your machine — you control it entirely
- **Telemetry data:** stored in our central database with industry-standard encryption

## 5. Your Rights

Under applicable data protection laws (including Colombian Ley 1581 de 2012 and the EU GDPR), you have the right to:

| Right | Description |
|-------|-------------|
| **Access** | Request a copy of your personal data |
| **Rectification** | Correct inaccurate personal data |
| **Deletion** | Request deletion of your personal data |
| **Portability** | Receive your data in a portable format |
| **Objection** | Object to processing based on legitimate interest |
| **Opt-out** | Disable telemetry collection at any time |

To exercise these rights, contact us at [legal@azelia.ai](mailto:legal@azelia.ai).

### 5.1 Colombian Users (Habeas Data)
Under Ley 1581 de 2012, you have the right to know, update, rectify, and delete your personal data. Data processing officer: legal@azelia.ai.

### 5.2 EU/EEA Users (GDPR)
For users in the European Economic Area, our legal basis for processing is explicit consent (onboarding telemetry toggle) and contract performance (account management). You may lodge a complaint with your local data protection authority.

## 6. Data Retention

- **Account data:** retained while your account is active, deleted within 30 days of account deletion request
- **Identifiable telemetry data:** linked to your user ID, deleted upon account deletion request
- **Anonymized, aggregated data:** retained indefinitely. Once anonymized, this data is irreversibly decoupled from your identity and cannot be attributed to any specific user, therefore deletion requests do not apply to it
- **Local data:** controlled entirely by you — delete it at any time from your machine

## 7. Children's Privacy

Azelia Clips is not intended for use by individuals under 16 years of age. We do not knowingly collect personal information from children.

## 8. Third-Party Services

Our software integrates with:
- **Supabase** — authentication and data storage ([supabase.com/privacy](https://supabase.com/privacy))
- **Google/YouTube APIs** — channel data and analytics ([Google Privacy Policy](https://policies.google.com/privacy))
- **AI Providers** (Groq, OpenAI, Anthropic, Google Vertex) — content processing (data sent per your configuration)

## 9. Open Source Transparency

Azelia Clips is open source software licensed under MIT + Commons Clause. You can review exactly what data is collected by inspecting the source code at [github.com/anju2246/azelia-clips](https://github.com/anju2246/azelia-clips).

## 10. Changes to This Policy

We will notify you of material changes via the software dashboard or email. Continued use after notification constitutes acceptance.

---

**Azelia** · [legal@azelia.ai](mailto:legal@azelia.ai)
