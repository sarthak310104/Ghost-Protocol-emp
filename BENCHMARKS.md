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

## Known issue found by this benchmark

`update_graph_and_baselines` hit real Postgres deadlocks under
concurrent load in this run -- roughly a **quarter of its invocations
failed** (`psycopg2.errors.DeadlockDetected` while updating
`service_nodes`/`service_edges` rows two concurrent worker processes
were touching in different orders). The task has no retry configured
(`@celery_app.task` with no `autoretry_for`/`retry_backoff`), so a
deadlocked batch's graph/baseline update is silently dropped -- not
retried, not logged anywhere surfaced to the dashboard. Under bursty
concurrent ingestion (the exact scenario this phase simulates), that
means a real, silent gap in derived state: baselines and edge discovery
for the lost batches never happen, with no visible error anywhere a
company operating this would see.

This is a correctness bug the benchmark surfaced, not something this
change fixes -- flagging it here rather than folding a fix into the
same change that just measures performance.