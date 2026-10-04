# Formy

*Advanced Dynamic Survey Platform*

A Django/DRF backend for enterprise survey design, collection and analysis:
a multi-step builder with cross-section conditional logic, anonymous
resumable submission, field-level encryption, per-survey RBAC, audit
logging and incrementally maintained analytics.

Django 6.1 · Python 3.14 · PostgreSQL 18 · Redis · Celery · React 19

---

## Quick start

```bash
make bootstrap     # containers, .env with real keys, migrations, demo survey
make dev           # API, worker and the React frontend, together
```

`make dev` needs Node and pnpm. Without them the backend still runs alone:

```bash
make run           # the API on :8000
make worker        # in another shell: exports and invitation batches
```

One Ctrl-C stops all three, so nothing is left holding port 8000. `make` on
its own lists every target.

- Frontend: <http://localhost:5173/>
- API docs: <http://localhost:8000/api/v1/docs/>
- Demo logins, password `demo-password`:
  - `demo-owner` — org owner: manages members, grants survey access
  - `demo-admin` — org admin: every survey, but cannot manage members
  - `demo-analyst` — member with an analyst grant on one survey only
  - `demo-root` — Django superuser, for `/admin/` only. Kept separate
    because `is_superuser` short-circuits every permission check

---

## The shape of it

```
formy/       settings, urls, Celery app -- the wiring, no domain logic
frontend/    React + TypeScript: the builder, the respondent form, results
core/        UUIDv7 base model, encryption, audit helpers, API plumbing
accounts/    Organization, Membership
surveys/     Survey, SurveyVersion, Section · condition evaluator ·
             publish pipeline · capability model · schema cache
responses/   Submission, Answer, SubmissionFile · the write path
analytics/   SurveyStat, FieldAggregate · rollups and reporting
exports/     CSV extracts as tracked, audited jobs
invitations/ distributing a survey to an audience
```

The commit history is the design document: each commit explains the
decision it makes and what the alternative cost.

---

## The decisions that matter

- **Answers are pinned to a `SurveyVersion`, not a `Survey`.** A published
  version is immutable, so editing a live survey cannot change how answers
  already collected are read — and the schema can cache without
  invalidation. v2 derives from v1 keeping field ids, so analytics align.
- **Conditional logic is one evaluator, run server-side.** The client is
  told what is visible so it can render; the server re-derives it on write,
  so no request can answer a hidden field, skip a required one, or pick an
  option earlier answers filtered away.
- **A non-visible field reads as absent, and absent compares false.**
  Otherwise a stale answer keeps downstream fields alive — answer Saudi
  Arabia, pick Riyadh, switch to Egypt, and the district question lingers.
  Its pair: *hidden implies not required*, or an invisible field blocks
  submission forever.
- **Visibility belongs to fields, not sections.** A section renders while
  any of its fields is visible, so there is no precedence to reconcile.
- **Field order is explicit.** `Section.content` is jsonb and Postgres
  sorts jsonb object keys, so insertion order is not preserved. It only
  looked correct because UUIDv7 is time-ordered and creation order happened
  to match.
- **Encryption is per field, AES-256-GCM**, with a per-row nonce and AAD
  binding each ciphertext to `submission:field`, so a ciphertext copied
  between rows fails to decrypt. Encrypted fields cannot be aggregated, and
  results say why rather than showing an empty chart.
- **Percentages count eligible respondents, not all of them.**
  `FieldAggregate` tracks `eligible_count` apart from `answered_count`,
  because a conditional question's denominator is not the response total.
- **Aggregates are maintained incrementally**, with one atomic upsert per
  field, so concurrent submissions cannot lose increments. The results
  payload is cached on the data's own clock — a key including
  `max(updated_at)` — so it can never go stale and never needs
  invalidating.
- **Access control is two layers.** Querysets decide what exists — an
  invisible survey is 404, since 403 would confirm the id and turn guessing
  into tenant enumeration. Capabilities then decide what may be done:
  views ask `can view PII`, never `is analyst`.
- **Respondents are anonymous**, so the resume token is the whole
  authorization story for a draft: 32 bytes, expiring, sent as a header
  rather than in a URL, cleared on completion. Their IP is stored hashed.

---

## API

Everything is under `/api/v1/`. The version is in the path so a deployed
client is pinned to a contract and a future v2 can run alongside v1.

Send credentials as `Authorization: Token <value>`. Tokens rather than JWTs
because they revoke immediately; the enterprise upgrade is SSO, not a
different bearer format.

| | |
|---|---|
| `POST /auth/token/` | exchange credentials for a token |
| `POST /auth/token/revoke/` | revoke it; takes effect immediately |
| `GET /auth/whoami/` | identify the caller |

### Staff — authenticated, authorised per survey

| | |
|---|---|
| `GET /organizations/` | organizations you belong to |
| `GET POST /organizations/{id}/members/` | org membership (owner only) |
| `GET PATCH DELETE /members/{id}/` | change or revoke a membership |
| `GET POST /organizations/{id}/surveys/` | list and create |
| `GET PATCH DELETE /surveys/{id}/` | |
| `GET PATCH DELETE /o/{org}/surveys/{slug}/` | the same survey at a readable address |
| `GET POST /surveys/{id}/access/` | grant a per-survey role (needs `access.grant`) |
| `GET PATCH DELETE /access/{id}/` | change or revoke one grant |
| `GET POST /surveys/{id}/versions/` | creating one derives from the latest published |
| `GET /versions/{id}/` | assembled schema |
| `GET POST /versions/{id}/sections/` | builder |
| `GET PATCH DELETE /sections/{id}/` | one section; refused once the version is published |
| `POST /versions/{id}/publish/` | validate, order, freeze |
| `GET /versions/{id}/results/` | aggregate analytics |
| `GET /surveys/{id}/results/` | the same, for the latest published version |
| `GET /versions/{id}/submissions/` | individual responses |
| `GET /submissions/{id}/answers/` | one response, decrypted per capability |
| `GET POST /versions/{id}/invitations/` | send the survey to a list |
| `GET /files/{id}/download/` | download an uploaded file (needs PII capability) |
| `GET POST /versions/{id}/exports/` | request a CSV |
| `GET /exports/{id}/download/` | |

### Respondents — anonymous, `X-Resume-Token` header

| | |
|---|---|
| `POST /public/invitations/{token}/redeem/` | open the survey behind an invitation link |
| `POST /public/versions/{id}/submissions/` | start; returns the token once |
| `GET /public/submissions/{id}/` | state: schema, answers, visibility, options |
| `PATCH /public/submissions/{id}/` | autosave a partial batch |
| `POST /public/submissions/{id}/files/` | upload a file; returns the id to answer with |
| `POST /public/submissions/{id}/submit/` | finalise |

Field ids are UUIDs minted client-side, so an entire multi-step survey can
be composed offline and posted section by section with cross-section
references already resolved. Each autosave response carries re-resolved
`visible`, `required` and `options`, so the next step is driven by what the
server now shows. `scripts/e2e_smoke.py` walks the whole flow over HTTP —
build, publish, answer, upload, submit, export — and is the executable
version of a worked example.

What `curl` cannot get past, because the server re-derives rather than
trusting the client: answering a hidden field (accepted, since the client
may be a step behind, but not stored), choosing an option earlier answers
filtered away, and submitting with a required field unanswered. Autosave
never complains about a half-filled form; submit does.

### Roles

| Scope | Role | |
|---|---|---|
| Organization | `owner` | everything, including member management |
| | `admin` | full access to every survey in the org |
| | `member` | **no** survey access until granted one |
| Survey | `editor` | build and publish; aggregate results only |
| | `analyst` | read responses including decrypted PII; export |
| | `viewer` | aggregate results only |

An editor can design a survey but cannot open an individual response — the
person who builds a form should not automatically read the personal data it
collects. Org roles and survey roles are disjoint enums, which is what
removes any precedence rule between an org grant and a survey grant.

---

## Testing

453 tests. `make check` runs lint, formatting, migration drift and the
suite. Each app keeps its own `tests/` package, Django-style, with shared
fixtures in the root `conftest.py`.

Worth knowing about: `core/tests/test_security.py` (injection, XSS, IDOR,
mass assignment, exposure), `core/tests/test_no_n_plus_one.py` (asserts the
query count is constant in the row count, which catches the regression a
fixed budget cannot) and `test_performance.py` (absolute budgets),
`surveys/tests/test_evaluation.py` (the evaluator, including the
stale-answer cascade), and `analytics/tests/test_rollups.py` (denominators,
atomicity, rebuild fidelity).

Three checks need a running server, because they test what a test suite
structurally cannot:

| | |
|---|---|
| `make e2e` | 87 checks over real HTTP. Every API test uses `force_authenticate`, which bypasses authentication entirely — this is what caught an API no client could log into |
| `make perf` | 40 concurrent submissions, asserting no counter increments are lost. pytest-django wraps each test in a transaction, so in-process "concurrency" serialises and the race never happens |
| `make load-headless` | Locust profile that fails on latency thresholds, not just prints numbers |

`loadtest/README.md` has the measured figures and says which number would
indicate the rollups had stopped being maintained incrementally.

A few tests pin properties that are easy to break silently: publishing v1,
editing v2, and asserting v1's schema is unchanged; rebuilding aggregates
from stored answers and getting identical numbers, which is the evidence
no `visible_fields` column is needed; and walking every scoped view to
assert it carries a capability check, after an early version of the mixin
left them all authorizing everything.

The frontend mirrors the evaluator in TypeScript so the form responds
instantly. `pnpm --dir frontend fixtures` regenerates parity fixtures from
the real Python evaluator and the TypeScript tests assert against them —
divergence would silently discard a respondent's answer.

---

## Not built, deliberately

Each with the signal that would bring it back:

- **Nested condition groups.** Flat `all`/`any` is a strict subset of the
  nested form, so nesting can be added later without migrating a single
  stored survey. Bring it back when an author actually needs
  `A and (B or C)`.
- **Key rotation.** Needs a keyring, a key id on every encrypted row and a
  background re-encryption job. Bring it back before the first compliance
  review, or immediately if a key is ever exposed.
- **Tamper-evident audit storage.** The log is ordinary rows, so database
  access can edit it. Hash-chain entries or ship to append-only storage
  when the audit trail itself must be evidence.
- **Table partitioning and archival tiering.** `make load-headless`
  records the figure that would signal it: answer-table growth where index
  maintenance, not query plans, becomes the limit.
- **Regex operators and cross-field comparison.** Both widen the rule
  grammar; regex also needs a safety story for catastrophic backtracking.
- **Invitation bounce handling and unsubscribe.** Needs a provider webhook
  and a suppression list — a feature of its own, not a line in a task.
- **Read replicas and PgBouncer.** The settings already disable
  server-side cursors so transaction-mode pooling will work; add them when
  read traffic from dashboards competes with the write path.

---

## Production notes

`formy/settings/prod.py` turns on HSTS, secure cookies and SSL redirect,
and disables server-side cursors (PgBouncer in transaction mode cannot hold
them). WhiteNoise serves static files with hashed names, so the admin and
the API docs work without a second process in front.

**Required at startup**, each `required=True` so a missing one is refused
when the process boots rather than failing confusingly later:

| | |
|---|---|
| `DJANGO_SECRET_KEY` | |
| `DJANGO_ALLOWED_HOSTS` | comma separated |
| `FIELD_ENCRYPTION_KEY` | 32 bytes base64; never change it once answers exist |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | needed behind a TLS-terminating proxy for the admin |
| `EMAIL_HOST` | the invitation relay; development prints to the console instead |

```bash
python manage.py migrate --settings=formy.settings.prod
python manage.py collectstatic --noinput --settings=formy.settings.prod
celery -A formy worker -Q rollups,exports,mail    # one per queue, or all three
```

Three deployment constraints:

- **Uploads go to local disk, deliberately**, so this runs as **one web
  process** — a second instance cannot read what the first stored, and an
  ephemeral filesystem loses files on redeploy. It buys a working upload
  flow with no object store to configure; swapping `STORAGES["default"]`
  for S3 is the only change needed to scale out.
- **The frontend expects the same origin.** It calls `/api/v1` relatively,
  so serving it from the API's host needs no configuration. A different
  origin needs `django-cors-headers` and `VITE_API_BASE`.
- **The SPA needs a catch-all rewrite.** Deep links like `/s/{id}` are
  client routes, so unknown paths must return `index.html` or a
  respondent's resume link 404s.

A CDN can front `GET /api/v1/versions/{id}/` once `Cache-Control` and
`ETag` are added to that view: a published version is immutable, so it is
the one response that can be cached indefinitely.
