# 👻 Ghost Protocol

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
| Incident correlation (union-find across the graph) | done | `app/incident/correlate.py` |
| Deployment markers + correlation | done | `app/models/deployment.py`, `POST /v1/deployments` |
| Simulation (statistical mean-reversion + blast radius, 95% CI on improvement) | done, scoped | `app/simulation/engine.py` |
| Evidence layer (structured schema: observations/dependencies/timeline/deployments/simulation) | done | `app/evidence/`, `GET /v1/incidents/{id}/evidence` |
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

## Simulation is not reasoning

The simulation engine answers "what does our data suggest would
happen," with a 95% confidence interval on the projected value *and*
on the improvement percentage itself (not just a point estimate) --
never "this is definitely the fix." Current scope: statistical
mean-reversion (projecting an anomalous metric back toward its own
historical baseline) plus a blast-radius report of what else is
affected. Counterfactual parameter simulation (e.g. "Redis TTL 30s ->
300s, predicted P99 -61%") is on the roadmap (see Phase 6 below) but
not yet implemented -- the current engine projects reversion-to-normal,
not the effect of an arbitrary hypothetical parameter change.

## Tech stack

FastAPI + AsyncIO · TimescaleDB · Redis + Celery · Docker Compose ·
Helm (planned) · Next.js + TypeScript (frontend, not yet built)

## Roadmap

- **Phase 1 -- Telemetry**: workspace + API key auth, OTLP ingestion, queueing, TimescaleDB storage, service extraction — **done**
- **Phase 2 -- Behavioral Graph**: service graph, dependency edges, edge metrics, rolling baselines — **done**
- **Phase 3 -- Bottleneck Analysis**: critical-path, fan-in/fan-out, saturation, structural risk ranking — **done**
- **Phase 4 -- Incident Detection**: anomaly detection, signal correlation, incident timelines, deployment correlation — **done**
- **Phase 5 -- Evidence**: evidence schema, incident evidence API, timeline generation, deployment context, historical comparisons — **done**
- **Phase 6 -- Simulation**: statistical impact estimation with confidence intervals — **done** (mean-reversion scope); counterfactual parameters — **not yet**
- **Phase 7 -- Platform**: dashboard, workspace management, OTel onboarding docs, Helm — **not yet**

## Running locally

```bash
cp .env.example .env
docker compose up
```

Then point an OTel collector's `otlphttp` exporter at
`/v1/traces` and `/v1/metrics` with the workspace API key from
`POST /v1/admin/workspaces` (requires `X-Admin-Secret: <GHOST_SECRET_KEY>`).

Note: `alembic/` is wired to the models but no migration has been
generated yet -- run `alembic revision --autogenerate -m "init"`
against a live Postgres first.
