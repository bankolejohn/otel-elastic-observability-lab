# ADR-0009: Elastic Cloud credentials via a gitignored `.env` file

Date: 2026-10-29
Status: Accepted

## Context

Stage D is the first point this project needs a real secret (an
Elasticsearch API key) and a real external endpoint. They must reach the
`otel-collector` container's config without ever being committed to the
repo or pasted into chat/logs.

## Decision

- `.env` (gitignored) holds `ELASTIC_ENDPOINT` and `ELASTIC_API_KEY`.
- `.env.example` (committed) documents the variable names and where to
  find real values, with both values left blank.
- `docker-compose.yml` passes them through to the `otel-collector`
  container's `environment:` block via `${ELASTIC_ENDPOINT}` /
  `${ELASTIC_API_KEY}` substitution (docker compose loads `.env`
  automatically).
- `otel-collector/config.yaml` reads them at the Collector's own startup
  via `${env:ELASTIC_ENDPOINT}` / `${env:ELASTIC_API_KEY}` -- two separate
  substitution steps (compose's, then the Collector's own), neither of
  which writes the real value into a file that gets committed.
- Throughout setup, the API key was never pasted into chat; the raw
  Elasticsearch *endpoint* was pasted a few times for debugging, which is
  fine -- it's a hostname, not a credential.

## Alternatives considered

- **Docker secrets / a vault (e.g. HashiCorp Vault, AWS Secrets
  Manager).** The correct answer for a real production system, and worth
  knowing exists -- but a meaningful operational dependency to stand up
  for a single local learning project with one secret. Revisit if this
  project ever needs to model production secret rotation specifically as
  a lesson.
- **Hardcoding values directly in `otel-collector/config.yaml`.**
  Rejected outright -- the config file is committed, and this would leak
  the key into git history the moment it's pushed anywhere.

## Consequences

- Anyone cloning this repo must create their own `.env` from
  `.env.example` and their own Elastic Cloud trial before Stage D works --
  expected and documented in the stage doc.
- `.env` existing locally but un-committed means `docker compose` commands
  only work correctly from a shell in this project directory with that
  file present; CI or another machine would need its own.

## Revisit when

If this project is ever deployed somewhere other than one person's local
machine, or if secret rotation/expiry becomes a lesson worth teaching.
