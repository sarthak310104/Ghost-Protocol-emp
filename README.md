# Ghost Protocol

**Observe. Model. Detect. Simulate.**

Ghost Protocol is a behavioral engineering platform for understanding
how software systems behave in production. It ingests telemetry,
builds a continuously updated behavioral model, identifies structural
bottlenecks and incidents, correlates failures across dependencies,
and runs statistical what-if simulations to estimate the impact of
potential changes.

It answers:

> What is happening in the system, what changed, what is connected to
> it, and what does the data predict will happen next?

## Core philosophy: measurement, not explanation

Ghost determines things that can be derived from the system's
observable behavior -- baselines, dependency structure, anomalies,
and the statistically expected effect of a change. It deliberately
stops short of asserting a root cause:

> "Historical data suggests changing X is associated with Y."
> — this is analysis, and it's what Ghost does.
>
> "Therefore X is definitely the root cause."
> — that's a different kind of claim, and Ghost doesn't make it.

That boundary is intentional and shows up directly in the code: the
simulation engine (`app/simulation/engine.py`) reports statistical
projections with the method used and no causal claims; nothing in
this repo generates a "root cause" statement.

## Core loop

```
PRODUCTION SYSTEM
      │
      ▼
  INGESTION
      │
      ▼
BEHAVIORAL MODEL ── baselines / dependencies / capacity
      │
      ▼
STRUCTURAL ANALYSIS (bottleneck engine)
      │
      ▼
ANOMALY DETECTION
      │
      ▼
INCIDENT CORRELATION
      │
      ▼
   EVIDENCE
      │
      ▼
  SIMULATION
      │
      ▼
QUANTIFIED RESULTS
```

## What's implemented

| Component | Status | Where |
|---|---|---|
| OTLP ingestion (traces + metrics, JSON) | done | `app/ingestion/`, `app/api/routes/ingest.py` |
| Behavioral graph (auto-discovered nodes/edges) | done | `app/graph/topology.py`, `app/graph/repo.py` |
| Dual baselines (fast "current" EWMA vs slow "reference" snapshot) | done, scheduled hourly | `app/graph/baseline.py`, `app/graph/reference.py` |
| Bottleneck engine (fan-in/fan-out, critical-path, risk score) | done | `app/bottleneck/engine.py`, `/v1/bottlenecks` |
| Anomaly detection (z-score vs reference baseline) | done | `app/incident/detect.py` |
| Incident correlation (union-find across the graph, matched on `last_seen_at` so a still-ongoing incident never silently splits into duplicates) | done | `app/incident/correlate.py` |
| Deployment markers + correlation | done | `app/models/deployment.py`, `POST /v1/deployments` |
| Simulation (statistical mean-reversion + blast radius, 95% CI on improvement) | done, scoped | `app/simulation/engine.py` |
| Cohort comparison (concurrent canary/rollout traffic, self-joined from raw spans, zero ingestion changes) | done | `app/cohort/`, `POST/GET /v1/cohort-dimensions`, `GET /v1/cohort-analysis` |
| Evidence layer (structured schema: observations/dependencies/timeline/deployments/simulation) | done | `app/evidence/`, `GET /v1/incidents/{id}/evidence` |
| Multi-workspace isolation, API key auth/revocation | done | `app/api/deps.py`, `app/models/workspace.py` |
| Frontend / dashboard | not started | — |

## Evidence

The evidence Ghost produces for an incident is what powers the
dashboard and the incident API -- `GET /v1/incidents/{id}/evidence`
assembles it into this shape (`app/evidence/schema.py`,
`app/evidence/builder.py`):

```json
{
  "incident": { "id": "incident-1842", "service": "checkout" },
  "observations": [
    { "metric": "checkout->redis latency_p99_ms", "baseline": 420.0, "current": 4800.0 }
  ],
  "dependencies": ["checkout->redis", "checkout->postgres"],
  "timeline": [
    { "kind": "incident_opened", "message": "...", "occurred_at": "..." }
  ],
  "deployments": [
    { "service_name": "checkout", "version": "v482", "deployed_at": "...", "minutes_before_incident": 4.2 }
  ],
  "simulation_results": []
}
```

Metric names carry the edge prefix (`"checkout->redis latency_p99_ms"`)
since Ghost's anomalies are per-edge, not per-service. Deployments are
matched by service name within a 60-minute lookback before the
incident's start time; nothing infers "this deployment caused it," it's
just surfaced as correlated-in-time context (`POST /v1/deployments` is
how a CI/CD pipeline records one).

Evidence merges on `(edge, metric)` rather than appending on every scan
cycle -- an anomaly that's still ongoing when the next 30s scan runs
(the common case) updates its existing entry in place instead of
growing the evidence list without bound for as long as the incident
stays open. Diagnosis attempts against an external reasoning service
follow the same discipline: only a newly-opened incident, a severity
escalation, or a 15-minute cooldown since the last attempt triggers a
new call, so a long-running incident doesn't retry indefinitely.

## Simulation is not reasoning

The simulation engine answers "what does our data suggest would
happen," with a 95% confidence interval on the projected value *and*
on the improvement percentage itself (not just a point estimate) --
never "this is definitely the fix." Two independent methods:

- **Statistical mean-reversion** (`app/simulation/engine.py`): projects
  an anomalous metric back toward its own historical baseline, plus a
  blast-radius report of what else is affected, matched on the exact
  edges involved rather than on service names -- an unrelated healthy
  edge that happens to share a service name with the incident (e.g.
  another caller of a busy shared cache) is correctly reported as
  blast radius, not misclassified as part of the incident itself.

- **Concurrent cohort comparison** (`app/cohort/`): if a company's
  canary/gradual rollout tags spans with a registered attribute (e.g.
  `config.redis_ttl_seconds`), Ghost compares latency between whatever
  values of that attribute are currently co-occurring on the same
  edge -- e.g. 8% of traffic at TTL=300s against the rest still at
  30s, observed over the same recent window. This is genuinely
  stronger evidence than before/after mean-reversion, since both
  cohorts run concurrently and aren't confounded by whatever else
  changed that week -- but it's still an association, not a randomized
  experiment, and the output says exactly that (`method:
  "two_sample_z_approximation"`, explicit 95% CI, a documented minimum
  sample size before any comparison is computed at all). Requires zero
  ingestion changes -- `Span.attributes` already stores every OTel
  span attribute, so this queries data that's already there the
  moment a company starts tagging spans. Register a dimension via
  `POST /v1/cohort-dimensions`, query on-demand via
  `GET /v1/cohort-analysis`, or let it surface automatically: when a
  registered dimension has concurrent data on an incident's edge, it's
  attached to that incident's evidence (`cohort_comparisons`)
  alongside the mean-reversion projection, with no separate request
  needed.

This closes most of the original "counterfactual parameter simulation"
gap (e.g. "Redis TTL 30s -> 300s, predicted P99 -61%") for companies
already running canary/gradual rollouts. What's still not covered:
retrospective comparison against a *past* config change with no
concurrent cohort (Option A from the design discussion -- mining
historical before/after when a value changed once, rather than two
values running side by side right now), and true what-if simulation
for a company with no rollout tooling at all, which remains out of
scope without the sandboxed-replica infrastructure explicitly deferred
at the start of this project.

## Tech stack

FastAPI + AsyncIO · TimescaleDB · Redis + Celery · Docker Compose ·
Helm (planned) · Next.js + TypeScript (frontend, not yet built)

## Roadmap

- **Phase 1 -- Telemetry**: workspace + API key auth, OTLP ingestion, queueing, TimescaleDB storage, service extraction — **done**
- **Phase 2 -- Behavioral Graph**: service graph, dependency edges, edge metrics, rolling baselines — **done**
- **Phase 3 -- Bottleneck Analysis**: critical-path, fan-in/fan-out, saturation, structural risk ranking — **done**
- **Phase 4 -- Incident Detection**: anomaly detection, signal correlation, incident timelines, deployment correlation — **done**
- **Phase 5 -- Evidence**: evidence schema, incident evidence API, timeline generation, deployment context, historical comparisons — **done**
- **Phase 6 -- Simulation**: statistical impact estimation with confidence intervals — **done** (mean-reversion + concurrent cohort comparison); retrospective historical-config-change correlation and true sandboxed what-if simulation — **not yet**
- **Phase 7 -- Platform**: dashboard, workspace management, OTel onboarding docs, Helm — **not yet**

## Tested

The core pipeline (ingestion → behavioral graph → bottleneck detection
→ anomaly detection → incident correlation → evidence → simulation)
has been run end-to-end against a live Postgres + Redis + Celery
stack, including:

- OTLP trace and metric ingestion (both `gauge` and `sum` metric types)
- Multi-edge incident correlation -- simultaneous anomalies across
  different edges correctly merge into one incident, not several
- Blast-radius reporting against a real multi-service topology
- Multi-workspace data isolation and API key revocation
- Incident resolve/recurrence handling
- Cohort comparison end-to-end: dimension registration, on-demand
  analysis with real computed statistics, the small-sample-size and
  no-data guardrails, and automatic attachment to an incident's
  evidence when concurrent cohort data exists for its edge
- The full Alembic migration chain, from empty database to current
  schema, in one run

**Not yet verified:** TimescaleDB hypertable conversion
(`migrations/001_hypertables.sql`) has been checked for correctness
against the current schema but not executed against a real
TimescaleDB instance; and the external-reasoning happy path has no
counterpart service to test against yet.

## Running locally

```bash
cp .env.example .env
docker compose up -d --build
docker compose run --rm api alembic upgrade head
```

Then point an OTel collector's `otlphttp` exporter at
`/v1/traces` and `/v1/metrics` with the workspace API key from
`POST /v1/admin/workspaces` (requires `X-Admin-Secret: <GHOST_SECRET_KEY>`).