# SECURITY — Threat model and controls

**Status:** Security requirements proposed before implementation. These are controls to build and verify, not claims of existing protection.

## 1. Threat model and assets

**Assets:** accounts/sessions, saved preferences, interaction history, product catalog integrity, model artifacts, API/LLM keys, agent tools, training datasets, deployment credentials.

**Trust boundaries:** browser ↔ API; API ↔ database/vector store; agent ↔ tool dispatcher; retrieved product/review text ↔ LLM prompt; training data ↔ model artifacts; CI ↔ deployment.

**Adversaries:** unauthenticated API users, malicious accounts, poisoned/review prompt-injection content, data-poisoning contributors, compromised dependencies, and leaked secrets.

## 2. Identity and authorization

- MVP guest sessions must be opaque, expiring and scoped; signed-in identity strategy remains TBD.
- Server-side authentication and authorization on every owner-scoped resource. Object IDs are not proof of permission (IDOR prevention).
- Admin-only catalog/model promotion endpoints guarded with least privilege and audit logs.
- Consider CSRF protection for cookie-authenticated mutations; use secure, HttpOnly, SameSite cookies and TLS.
- Restrict CORS to intended origins; rate-limit auth, agent, search and feedback endpoints.

## 3. AI/agent security

- Treat product titles, reviews, descriptions, search results and tool responses as untrusted **data**. Never execute instructions found inside them.
- Strict function/tool allowlist, Pydantic validation, max steps, deadlines, token/cost caps, restricted provider credentials.
- Agent must not call raw SQL, shell, arbitrary URLs or privileged catalog update tools.
- Enforce user-scoped access within tool implementations; never trust LLM-generated user IDs.
- Final product and budget checks happen in deterministic code after ranking/agent workflow.
- Use curated, structured evidence for explanations; do not infer missing specs, current availability or real purchase guarantees.
- Red-team: prompt injection in a review, JSON schema escape, unauthorized profile lookup, budget bypass, tool-loop exhaustion, hallucinated product ID.

## 4. API, data and infrastructure

- Validate request size, content type, enums, numeric bounds, currency, pagination and product IDs.
- Parameterized queries via ORM/data access; avoid string-built SQL.
- Encrypt in transit; database and vector store private on local/network interface, not Internet-exposed by default.
- Secrets in environment/secret manager; `.env.example` contains names only; rotation procedure before external deployment.
- Dependency vulnerability scanning, pinned lockfiles, minimal container images, non-root containers and image provenance.
- Restrict artifact deserialization; do not load untrusted pickle/torch checkpoints without provenance review.
- Telemetry sanitization: no API keys, raw auth tokens, or unnecessary user text in logs.
- Backups encrypted and restore tested; documented deletion and incident response.

## 5. Abuse and resource limits

Limits for request frequency, concurrent agent runs, number of candidates, text lengths, DB query deadlines, vector query timeouts, training GPU/CPU consumption and LLM budget. Return explicit 429/503 errors rather than unbounded retry loops.

## 6. Release checklist

- [ ] Threat model reviewed and prioritized
- [ ] Secrets scan and dependency scan clean, or justified exceptions recorded
- [ ] AuthN/AuthZ/IDOR tests pass
- [ ] Agent prompt-injection and tool allowlist tests pass
- [ ] Mandatory constraints cannot be bypassed
- [ ] Data retention, export and deletion behaviors verified
- [ ] Container network and production TLS checked
- [ ] Redacted traces and audit trail verified
- [ ] Backup restoration exercised

## 7. Security exception protocol

No AI coding agent may weaken an existing control as a quick fix. Record the trade-off, required authorization, tests and remediation deadline. No production deployment with unresolved high-severity secret exposure or cross-user authorization flaws.
