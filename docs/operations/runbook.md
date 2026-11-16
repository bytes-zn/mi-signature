# Operations Runbook

Operational procedures for running MI Signature in production.

## 1. Deployment

```bash
cp .env.example .env
make secrets                 # prints OPERATOR_API_KEY, SECRET_ENCRYPTION_KEY, ...
# fill .env with the generated values and the Exchange Online egress ranges
make prod-up                 # docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

The production baseline (`ENVIRONMENT=production`) **refuses to start** when

- `OPERATOR_API_KEY` is the default value or shorter than 32 characters,
- `SECRET_ENCRYPTION_KEY` is missing,
- `SMTP_ALLOWED_HOSTS` is empty (open relay),
- `SMTP_INBOUND_REQUIRE_TLS` is disabled,
- `DEBUG` is enabled,
- the TLS certificate paths or `SMTP_RELAY_HOSTNAME` are missing.

Check the state of the stack:

```bash
docker compose ps
docker compose logs -f smtp
curl -fsS https://api.example.com/health
```

## 2. Required secrets

| Variable | Purpose | Rotation |
|---|---|---|
| `OPERATOR_API_KEY` | Platform administration | freely; the old key stops working immediately |
| `SECRET_ENCRYPTION_KEY` | Encrypts tenant secrets at rest | see below |
| `METRICS_TOKEN` | Protects `/metrics` | freely |
| `REDIS_PASSWORD` | Protects the cache | freely (restart Redis and API) |
| `POSTGRES_PASSWORD` | Protects the database | freely (restart DB and API) |

### Rotating the encryption key

The encryption key cannot be rotated in place: existing ciphertext would
become unreadable. Procedure:

1. Stop the API, worker and SMTP containers.
2. Export the old and the new key.
3. Run the re-encryption script against a database dump, or rotate the key
   by migrating the tenant secrets with a maintenance job.
4. Only then start the services with the new key.

Until the migration is complete, `SECRET_ENCRYPTION_KEY` must not change -
otherwise the Graph sync of the affected tenants fails.

## 3. Backup and restore

**PostgreSQL is the only stateful component that must be backed up.**

```bash
# daily dump
docker compose exec -T db pg_dump -U signature -Fc signature > backup-$(date +%F).dump

# restore into an empty database
docker compose exec -T db pg_restore -U signature -d signature --clean --if-exists < backup-2026-01-01.dump
```

Recommended:

- daily full dump, retained for 30 days,
- copy the dumps to a second host (they contain encrypted tenant secrets,
  but still personal data),
- **restore test at least quarterly** - an untested backup is no backup,
- target RPO 24 h, target RTO 2 h.

Not backed up (recoverable):

- Redis: only a cache of the directory data - rebuildable via `POST /api/v1/graph/sync`,
- TLS certificates: reissue with certbot.

## 4. Monitoring

| Signal | Source | Action |
|---|---|---|
| Liveness | `GET /health` (200/503) | container health check |
| Request rate, latency, errors | `/metrics` (Prometheus) | alert on error rate > 1 % |
| Rate limiting | `http_rate_limited_total` | alert on a sudden increase |
| Oversized bodies | `http_rejected_body_total` | investigate |
| Mail flow | `logs`: `smtp message processed and delivered`, `smtp delivery outcome uncertain` | every `uncertain` message is retried by Exchange |
| Audit trail | table `audit_logs` | review on request |

Recommended alerts:

- `smtp` container not healthy for 2 min,
- `/health` returns 503 for 2 min,
- `http_requests_total{status=~"5.."}` rate > 1/min,
- no `smtp message processed and delivered` log line for 15 min during
  business hours (mail flow is broken),
- disk usage > 80 % (log rotation is configured, but dumps also live there).

## 5. Incident procedures

### The SMTP container is down

1. `docker compose up -d smtp` - the listener accepts connections again.
2. Exchange retries the mail it could not deliver; nothing is lost.
3. If the cause was a crash loop, check `docker compose logs smtp` - the
   fail-safe design forwards every message it cannot sign unchanged, so
   mails keep flowing with and without signatures.

### Mails are delivered without a signature

Check the log sequence for the affected sender:

- `smtp sender domain not configured` - the sender domain is missing in
  `tenant.settings["accepted_domains"]`,
- `smtp no signature applied` - no rule matched the sender, or the sender
  is not part of the synced directory,
- `smtp processing failed` - the pipeline raised an exception; the
  original mail was forwarded unchanged.

### Suspected duplicate mails

The delivery path distinguishes three outcomes:

- rejected (5xx) - the original copy is sent as a fallback,
- deferred (4xx) - Exchange retries the message,
- uncertain - the connection broke in flight; **no second copy is sent**,
  Exchange retries the message instead.

`smtp delivery outcome uncertain` in the log means the message may have
been delivered. Ask the recipient, do not resend manually.

### Database unavailable

- The API returns 503 on `/health`; requests fail with a database error.
- The SMTP server keeps accepting mails and forwards them unchanged
  (fail-safe), so no mail is lost while the database is down.
- Restore: check `docker compose ps db`, then `docker compose logs db`.

## 6. Performance notes

The mail path resolves the tenant, the user, the rules, the template and
the campaign for every message. With a high mail volume:

- the directory data is cached in Redis (`GRAPH_CACHE_TTL_SECONDS`),
- `find_active_by_domain` loads the active tenants per message - with many
  tenants, add an index on `tenants.settings` and query the domain
  directly,
- the compiled templates and the parsed rule conditions are cached in the
  process.

## 7. Security checks before going live

- [ ] `OPERATOR_API_KEY` and `SECRET_ENCRYPTION_KEY` generated and set
- [ ] `SMTP_ALLOWED_HOSTS` contains the Exchange Online egress ranges
- [ ] TLS certificate installed, `SMTP_INBOUND_REQUIRE_TLS=true`
- [ ] `METRICS_TOKEN` set, `API_DOCS_ENABLED=false`
- [ ] `TRUSTED_HOSTS` set to the public hostnames
- [ ] TLS terminator in front of the API (`HTTPS_REDIRECT=true`)
- [ ] SPF of the sender domain contains the relay IP
- [ ] Backup configured and restore tested
- [ ] `alembic upgrade head` executed (`make migrate`)
