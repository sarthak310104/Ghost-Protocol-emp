# Benchmarks

Measured with `scripts/benchmark.py` against the real Celery/worker
architecture (`GHOST_SYNC_MODE=false`) -- not the free-tier sync-mode
path the live demo runs under. Sync-mode exists specifically so the
public demo doesn't need a paid persistent worker; benchmarking it would
mostly measure "how fast is one Python process," not the architecture
the roadmap is actually asking to prove out.

## How to reproduce

```bash
docker compose -f docker-compose.yml -f docker-compose.benchmark.yml up -d --build
docker compose exec api alembic upgrade head
docker compose exec api python scripts/benchmark.py
```

`docker-compose.benchmark.yml` is an additive override, not a permanent
config change: it mounts `scripts/` into the `api` container (the base
image doesn't ship it) and raises the per-workspace ingest rate limit
and max-spans-per-request ceiling far past their production defaults.
Those limits exist to stop one workspace from hammering a real
multi-tenant deployment; left at their defaults here, the benchmark
would mostly measure the rate limiter, not the ingestion path.

The script creates its own workspace, runs all four phases below, and
deletes that workspace's data as its last step (a full retention prune,
timed as part of phase 4) -- it never touches any other workspace,
including the public demo's.

## This run's environment

Run against natively-installed Postgres 16 + Redis 7 (same versions
`docker-compose.yml` pins) rather than the containers themselves --
container image pulls weren't available on the machine this particular
run was done on. Same code path either way: FastAPI via uvicorn, one
Celery worker process consuming all four queues
(`ingestion,graph,incident,reasoning`) at `--concurrency=4`, matching
`docker-compose.yml`'s worker command.

**2 vCPU / ~8GB.** That's a materially smaller machine than most people
would actually deploy this on, and it shows most in the phase-2 numbers
below -- treat the ingestion-throughput curve shape and the phase-4
query costs as the portable results, and the phase-2 absolute queue-wait
numbers as "what a 2-vCPU box looks like under a 100k-span burst,"
not a general claim about the architecture. Re-run on real target
hardware before using these for capacity planning.

Synthetic topology: 5-layer DAG (gateway -> 8 frontends -> 20 services
-> 14 data stores -> 7 infra), 50 services / 123 edges, every node
guaranteed reachable from the gateway so load actually reaches the
whole graph, not just whichever branch a random walk happened to favor.

## Results

### 1. Ingestion throughput

`POST /v1/traces`, ~15k spans per concurrency level.

| Concurrency | Spans/sec | Errors |
|---|---|---|
| 1  | 11,405 | 0 |
| 5  | 18,014 | 0 |
| 10 | 22,557 | 0 |
| 25 | 21,501 | 0 |
| 50 | 22,974 | 0 |

Scales close to linearly out to ~10 concurrent requests, then flattens
around 20-23k spans/sec -- the ingestion endpoint itself (bulk insert +
dispatch) isn't the bottleneck past that point; see phase 2.

### 2. Queue-wait vs. processing latency (100k-span burst, concurrency=40)

Queue-wait = time a task sat waiting after being dispatched, before a
worker picked it up. Processing = the worker's own reported runtime
once it started. Two different things on purpose: queue-wait says
something about worker capacity relative to incoming load, processing
says something about the task body's own cost.

| Task | n | queue-wait p50 | p95 | p99 | processing p50 | p95 | p99 |
|---|---|---|---|---|---|---|---|
| `ingest_spans_batch` | 459 | 86.8s | 158.0s | 165.8s | 61.7ms | 131.3ms | 176.0ms |
| `update_graph_and_baselines` | 372 | 4.1s | 5.4s | 6.0s | 1187ms | 3017ms | 4040ms |

Queue depth: `ingestion` peaked at 446 messages, drained by t+171s;
`graph` peaked at 4, drained by t+173s.

**Reading this correctly**: `ingest_spans_batch` itself is fast (p50
62ms -- it's a bulk insert) but its queue-wait is enormous, because one
worker process's task slots are shared, unprioritized, across all four
queues. `update_graph_and_baselines` (the actual bottleneck-engine
input -- baseline updates per edge) is the expensive task, at up to 4
seconds per batch at p99, and it head-of-line-blocks the cheap
ingestion work sitting behind it in the same worker's slot pool. On a
2-vCPU box this is severe; on real target hardware (or with ingestion
routed to a dedicated worker/queue with its own concurrency, which
`task_routes` already makes trivial -- it's one more `-Q` on a second
`celery worker` invocation) it would be far smaller, but the underlying
shape -- no priority separation between latency-sensitive ingestion and
CPU-heavier graph processing -- is real and independent of hardware.

### 3. API read latency (against the ~100k spans / 123 edges above)

100 requests per endpoint, sequential, after the phase-2 burst fully
drained (so these reflect steady-state read cost, not reads competing
with a live write burst).

| Endpoint | p50 | p95 | p99 |
|---|---|---|---|
| `/v1/bottlenecks` | 9.8ms | 13.9ms | 55.3ms |
| `/v1/services` | 7.7ms | 9.3ms | 9.5ms |
| `/v1/graph` | 9.0ms | 10.0ms | 11.5ms |
| `/v1/incidents` | 5.0ms | 6.4ms | 6.9ms |

All comfortably sub-15ms at p95 even with 123 edges of accumulated
history -- these compute on-demand from `ServiceEdge`/`ServiceNode`
rows scoped to one workspace (see `app/api/routes/bottlenecks.py`),
which stays cheap at this scale. The `/v1/bottlenecks` and `/v1/graph`
p99 outliers (55ms, 11.5ms) line up with requests that landed while the
phase-2 drain's last few writes were still committing.

### 4. DB performance

**Cohort analysis** (`GET /v1/cohort-analysis`, the heaviest read -- a
self-joined span aggregation): one edge tagged with a real concurrent
50/50 split (362 spans per cohort in this run), 20 repeated queries
over a 24h window against the full accumulated span table.

| | p50 | p95 | p99 |
|---|---|---|---|
| cohort-analysis query | 40.6ms | 42.8ms | 43.0ms |

**Retention prune** (`prune_old_telemetry`, run the same way the
scheduled Celery task calls it): deleted the full accumulated dataset
from this run --

| Spans deleted | Metrics deleted | Elapsed |
|---|---|---|
| 175,335 | 0 | 0.17s |

## Known issue found by this benchmark (fixed)

`update_graph_and_baselines` hit real Postgres deadlocks under
concurrent load in the original run -- roughly a **quarter of its
invocations failed** (`psycopg2.errors.DeadlockDetected` while updating
`service_nodes`/`service_edges` rows two concurrent worker processes
were touching in different orders). The task had no retry configured,
so a deadlocked batch's graph/baseline update was silently dropped --
not retried, not logged anywhere surfaced to the dashboard. Under
bursty concurrent ingestion (the exact scenario this phase simulates),
that meant a real, silent gap in derived state: baselines and edge
discovery for the lost batches never happened, with no visible error
anywhere a company operating this would see.

**Root cause and fix**: `update_graph_and_baselines` iterated
`services_seen` (a `set`) and the derived `edges` (ordered however
spans happened to arrive in that batch) to decide which
nodes/edges to touch. Two concurrent batches sharing overlapping
existing rows -- the common case under real traffic -- would reach
those rows in different relative orders, and Postgres deadlocks when
two transactions lock the same rows in opposite order. Fixed by
sorting both before iterating (`sorted(services_seen)`,
`sorted(edges, key=lambda e: (e.caller, e.callee))`), so every
transaction touching a given workspace's rows does so in one fixed,
deterministic order -- removing the opposite-order case entirely
rather than papering over it with retries.

Re-running this benchmark's phase 2 after the fix (40,040-span burst,
concurrency 40, same 50-service topology) surfaced **zero** deadlocks
across 119+ completed `update_graph_and_baselines` invocations, versus
~25% failing before.

**A second, smaller bug the same re-run surfaced**: with the deadlock
gone, a handful of invocations (3 of ~122, ~2.5%) hit a *different*
failure -- `psycopg2.errors.UniqueViolation` on
`uq_service_workspace_name`/`uq_edge_workspace_pair`. This is the
classic check-then-insert race: two concurrent batches both see "no
row yet" for the same brand-new service/edge, and both try to insert
it; sorting fixes lock order on *existing* rows but can't fix a race
between two first-time creates of the same new row. Fixed in
`app/graph/repo.py`'s `get_or_create_node`/`get_or_create_edge`: the
insert now happens inside a savepoint (`db.begin_nested()`), and a
unique-violation there is caught and resolved by re-selecting the row
the other transaction actually committed, instead of aborting the
whole batch's transaction. Confirmed clean (zero errors of any kind in
the worker log) on a second re-run after this fix.

## Queue separation (implemented)

Phase 2's original finding above ("Reading this correctly") was that
`ingest_spans_batch` -- fast on its own, ~60-70ms processing time --
was getting stuck behind `update_graph_and_baselines` because both
shared one worker process's task slots. `task_routes` already put
them on separate Celery queues; what was missing was actually
consuming those queues with separate worker processes, so cheap
ingestion work couldn't get starved behind expensive graph work
anymore. `docker-compose.yml` now runs `worker-ingestion` (queue:
`ingestion` only) and `worker-graph` (queues: `graph,incident,
reasoning`) instead of one `worker` consuming all four.

Re-ran the same 40,040-span/concurrency-40 burst with two separate
2vCPU worker processes (`--concurrency=2` each, same total slot count
as the single 4-slot worker it replaces) instead of one:

| Task | queue-wait p50 (before) | queue-wait p50 (after) | queue-wait p99 (before) | queue-wait p99 (after) |
|---|---|---|---|---|
| `ingest_spans_batch` | 13,202ms | **4,307ms** | 30,094ms | **7,951ms** |
| `update_graph_and_baselines` | 3,838ms | 12,187ms | 4,933ms | 25,065ms |

Ingestion got faster and its queue drained sooner (t+12.6s vs.
t+30.6s) -- it's no longer waiting on whatever the graph queue happens
to be doing. But note what also happened: `update_graph_and_baselines`
got *slower*, not faster. That's not a regression introduced by this
change, it's the tradeoff made visible: the old single pool let
ingestion opportunistically borrow idle slots from graph's share (and
vice versa) when one queue was quiet; two fixed-size pools can't
borrow from each other, so each queue is now capped at exactly what
its own worker was given, no more, no less. On this benchmark's
2-vCPU box, splitting 4 slots into 2+2 has nowhere to pull extra
capacity from.

That's the correct tradeoff to make deliberately, not by accident: in
a real deployment, ingestion and graph workers should be sized
independently based on their actual task cost and how latency-
sensitive each one is (ingestion gates dashboard freshness and should
usually win more concurrency; graph processing can tolerate a longer
queue), not left to split whatever concurrency one shared process
happened to have. This change makes that possible -- `docker-
compose.yml`'s two worker commands can each take their own
`--concurrency` independently of each other -- but doesn't pick sizes
for you; the 2+2 split above is purely what this sandbox's CPU count
allowed for an apples-to-apples before/after comparison, not a sizing
recommendation.