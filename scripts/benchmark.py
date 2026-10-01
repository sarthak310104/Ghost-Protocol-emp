#!/usr/bin/env python3
"""
Ghost Protocol benchmark harness.

Measures, against the real Celery/worker architecture (not the free-tier
GHOST_SYNC_MODE path -- see README's "Free-tier deployment" section for
why those are different things worth measuring separately):

  1. Ingestion throughput   -- spans/sec accepted by POST /v1/traces
                                at increasing request concurrency.
  2. Queue-wait vs.
     processing latency     -- for ingest_spans_batch (bulk span insert)
                                and update_graph_and_baselines (the
                                actual graph/baseline algorithm), split
                                via Celery task events into "time spent
                                waiting in the queue" and "time spent
                                actually running," plus queue depth
                                sampled over the course of the burst.
  3. API read latency        -- p50/p95/p99 for /v1/bottlenecks,
                                /v1/services, /v1/graph, /v1/incidents
                                against the real row counts the burst
                                above just produced (not the 6-service
                                demo topology).
  4. DB performance          -- cohort-analysis query latency (the
                                heaviest read: a self-joined span
                                aggregation) and a full retention-prune
                                pass, both at real accumulated row
                                counts.

Run inside the api container, against the benchmark compose override
(see docker-compose.benchmark.yml for why -- mainly: it raises the
per-workspace ingest rate limit past what a real deployment should
ever allow, on purpose, so this measures the ingestion path instead of
the rate limiter):

    docker compose -f docker-compose.yml -f docker-compose.benchmark.yml up -d --build
    docker compose exec api alembic upgrade head
    docker compose exec api python scripts/benchmark.py

Synthetic topology is a 5-layer DAG (gateway -> frontends -> services ->
data stores -> infra), sized ~50 services / a few hundred edges by
default -- big enough to exercise the bottleneck engine and cohort
queries at something past the 6-service demo topology's scale, without
needing a contrived seed.

This is a load generator hitting a real local deployment. It creates
its own workspace and deletes that workspace's data at the end (the
retention-prune phase, run last, on purpose) -- it does not touch any
other workspace.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import statistics
import sys
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

# /code/scripts/benchmark.py -> add /code (the app package's parent) to
# sys.path. Not needed if this is ever run as `python -m scripts.benchmark`
# from /code, but plain `python scripts/benchmark.py` puts /code/scripts
# on sys.path[0] instead, which can't see the `app` package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.celery_app import celery_app  # noqa: E402
from app.core.config import get_settings  # noqa: E402


# --------------------------------------------------------------------------
# Synthetic topology
# --------------------------------------------------------------------------

@dataclass
class EdgeSpec:
    caller: str
    callee: str
    latency_mu: float      # lognormal mu (ln-space) for this edge's duration_ms
    latency_sigma: float
    error_rate: float


@dataclass
class Topology:
    layers: list[list[str]]
    root: str
    edges: dict[tuple[str, str], EdgeSpec] = field(default_factory=dict)
    graph: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))

    @property
    def all_edges(self) -> list[EdgeSpec]:
        return list(self.edges.values())


# Layer proportions: gateway, frontend, service, data, infra. A real
# system skews toward the middle "service" tier -- the gateway is one
# node by definition, and infra (caches/queues/DB shards) tends to be
# the smallest, most fanned-in tier.
_LAYER_WEIGHTS = [1, 8, 20, 14, 7]  # sums to 50 for the default --services=50
# Per-layer edge latency distribution (mu, sigma in ln-space) -- deeper
# layers (closer to a datastore) run faster per-hop but with more
# relative variance; frontend/service hops carry more business logic.
_LAYER_LATENCY = [
    (math.log(8), 0.35),    # gateway -> frontend
    (math.log(35), 0.55),   # frontend -> service
    (math.log(60), 0.70),   # service -> data
    (math.log(6), 0.50),    # data -> infra
]
_LAYER_ERROR_RATE = [0.002, 0.004, 0.008, 0.003]


def build_topology(num_services: int, seed: int) -> Topology:
    rng = random.Random(seed)

    if num_services != 50:
        scale = num_services / 50
        sizes = [max(1, round(w * scale)) for w in _LAYER_WEIGHTS]
        sizes[0] = 1  # exactly one gateway, always
    else:
        sizes = list(_LAYER_WEIGHTS)

    names = ["gateway-00"]
    layer_names = [["gateway-00"]]
    prefixes = ["frontend", "service", "data", "infra"]
    for prefix, size in zip(prefixes, sizes[1:]):
        layer = [f"{prefix}-{i:02d}" for i in range(size)]
        layer_names.append(layer)
        names.extend(layer)

    topo = Topology(layers=layer_names, root="gateway-00")

    def add_edge(caller: str, callee: str, mu: float, sigma: float, err: float) -> None:
        if (caller, callee) in topo.edges:
            return
        # +/- jitter per edge so it's not the exact same distribution for
        # every edge in a layer -- a real system has some dependencies
        # that are just slower than their siblings.
        edge_mu = mu + rng.uniform(-0.15, 0.25)
        edge_sigma = sigma * rng.uniform(0.85, 1.2)
        edge_err = max(0.0, err * rng.uniform(0.3, 2.0))
        topo.edges[(caller, callee)] = EdgeSpec(caller, callee, edge_mu, edge_sigma, edge_err)
        topo.graph[caller].append(callee)

    for i in range(len(layer_names) - 1):
        callers = layer_names[i]
        callees = layer_names[i + 1]
        mu, sigma = _LAYER_LATENCY[i]
        err = _LAYER_ERROR_RATE[i]

        # Guarantee every node in this layer has at least one caller in
        # the layer above it, round-robin over the callers -- otherwise
        # a purely random per-caller fanout can (and, tested, reliably
        # does) leave whole branches of the topology unreachable from
        # the root, since nothing else calls into them. That's silently
        # fine for the ingestion-throughput phase (whatever spans get
        # generated still get sent), but it's fatal for the phase-2/
        # phase-4 cohort scenario, which picks one specific edge and
        # needs it to actually see traffic.
        shuffled_callees = list(callees)
        rng.shuffle(shuffled_callees)
        for idx, callee in enumerate(shuffled_callees):
            caller = callers[idx % len(callers)]
            add_edge(caller, callee, mu, sigma, err)

        # On top of the guaranteed spanning edges above, add realistic
        # extra fan-out so most callers have more than one downstream
        # dependency.
        for caller in callers:
            extra = rng.randint(1, 3)
            for callee in rng.sample(callees, min(len(callees), extra)):
                add_edge(caller, callee, mu, sigma, err)

        # Occasional skip-layer edge (frontend calling straight into data,
        # bypassing the service tier) -- real topologies aren't perfectly
        # layered. Kept rare so it doesn't dominate the edge count.
        if i + 2 < len(layer_names):
            skip_callees = layer_names[i + 2]
            for caller in callers:
                if rng.random() < 0.12:
                    callee = rng.choice(skip_callees)
                    if (caller, callee) not in topo.edges:
                        skip_mu = _LAYER_LATENCY[i + 1][0] + 0.2
                        topo.edges[(caller, callee)] = EdgeSpec(caller, callee, skip_mu, sigma, err)
                        topo.graph[caller].append(callee)

    return topo


# --------------------------------------------------------------------------
# Synthetic trace generation -> OTLP/HTTP+JSON payloads
# --------------------------------------------------------------------------

_MAX_TRACE_DEPTH = 8
_DESCEND_PROB = 0.72  # a trace doesn't necessarily touch every downstream edge


def _new_id(rng: random.Random, nbytes: int) -> str:
    return rng.getrandbits(nbytes * 8).to_bytes(nbytes, "big").hex()


def _gen_trace_spans(
    topo: Topology,
    rng: random.Random,
    now_ns: int,
    cohort_edge: tuple[str, str] | None = None,
    cohort_attr_key: str = "",
) -> list[dict]:
    """One synthetic trace: a span per hop walked from the gateway down
    through the topology, each span's duration/error sampled from its
    edge's distribution. Returns our own flat span dicts (converted to
    OTLP shape separately) -- one dict per span, in caller-before-callee
    order so building the OTLP payload is a straight pass."""
    trace_id = _new_id(rng, 16)
    spans: list[dict] = []
    t_cursor = now_ns

    root_span_id = _new_id(rng, 8)
    root_duration_ms = max(0.5, rng.lognormvariate(math.log(3), 0.3))
    spans.append({
        "service_name": topo.root, "span_id": root_span_id, "parent_span_id": None,
        "start_ns": t_cursor, "duration_ms": root_duration_ms, "is_error": False,
        "attributes": {},
    })

    def walk(caller: str, parent_span_id: str, parent_start_ns: int, depth: int) -> None:
        if depth > _MAX_TRACE_DEPTH:
            return
        for callee in topo.graph.get(caller, []):
            if rng.random() > _DESCEND_PROB:
                continue
            edge = topo.edges[(caller, callee)]
            duration_ms = max(0.1, rng.lognormvariate(edge.latency_mu, edge.latency_sigma))
            is_error = rng.random() < edge.error_rate
            attributes: dict = {}

            if cohort_edge is not None and (caller, callee) == cohort_edge:
                # Real concurrent canary split on this one edge: half the
                # traffic tagged "slow" cohort, genuinely slower, so
                # GET /v1/cohort-analysis has a real difference to find --
                # same idea as app/workers/tasks.py:seed_demo_workspace's
                # config.redis_ttl_seconds split, different attribute name
                # so it can't collide with a real demo workspace's data.
                if rng.random() < 0.5:
                    attributes[cohort_attr_key] = 30
                else:
                    attributes[cohort_attr_key] = 300
                    duration_ms *= rng.uniform(1.3, 1.7)

            span_id = _new_id(rng, 8)
            start_ns = parent_start_ns + rng.randint(0, 2_000_000)  # slight offset after parent starts
            spans.append({
                "service_name": callee, "span_id": span_id, "parent_span_id": parent_span_id,
                "start_ns": start_ns, "duration_ms": duration_ms, "is_error": is_error,
                "attributes": attributes,
            })
            walk(callee, span_id, start_ns, depth + 1)

    walk(topo.root, root_span_id, t_cursor, 1)
    for s in spans:
        s["trace_id"] = trace_id
    return spans


def _spans_to_otlp_payload(spans: list[dict]) -> dict:
    by_service: dict[str, list[dict]] = defaultdict(list)
    for s in spans:
        by_service[s["service_name"]].append(s)

    resource_spans = []
    for service, svc_spans in by_service.items():
        otlp_spans = []
        for s in svc_spans:
            start_ns = s["start_ns"]
            end_ns = start_ns + int(s["duration_ms"] * 1_000_000)
            attrs = [{"key": k, "value": {"intValue": v} if isinstance(v, int) else {"stringValue": str(v)}}
                     for k, v in s["attributes"].items()]
            otlp_spans.append({
                "traceId": s["trace_id"], "spanId": s["span_id"], "parentSpanId": s["parent_span_id"],
                "name": f"{s['service_name']}.handle", "kind": 2,
                "startTimeUnixNano": str(start_ns), "endTimeUnixNano": str(end_ns),
                "attributes": attrs,
                "status": {"code": 2} if s["is_error"] else {"code": 1},
            })
        resource_spans.append({
            "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": service}}]},
            "scopeSpans": [{"spans": otlp_spans}],
        })
    return {"resourceSpans": resource_spans}


def build_request_batches(
    topo: Topology,
    total_spans: int,
    spans_per_request: int,
    rng: random.Random,
    cohort_edge: tuple[str, str] | None = None,
    cohort_attr_key: str = "",
) -> list[dict]:
    """Pre-generate OTLP payloads up front so timing starts only at the
    HTTP-send phase, not generation."""
    batches: list[dict] = []
    now_ns = int(time.time() * 1_000_000_000)
    spans_so_far = 0
    while spans_so_far < total_spans:
        batch_spans: list[dict] = []
        while len(batch_spans) < spans_per_request and spans_so_far < total_spans:
            trace = _gen_trace_spans(topo, rng, now_ns, cohort_edge, cohort_attr_key)
            batch_spans.extend(trace)
            spans_so_far += len(trace)
        batches.append(_spans_to_otlp_payload(batch_spans))
    return batches


def count_spans_in_payload(payload: dict) -> int:
    return sum(len(scope["spans"]) for rs in payload["resourceSpans"] for scope in rs["scopeSpans"])


# --------------------------------------------------------------------------
# HTTP helpers
# --------------------------------------------------------------------------

async def _post_traces(client: httpx.AsyncClient, base_url: str, api_key: str, payload: dict) -> httpx.Response:
    return await client.post(
        f"{base_url}/v1/traces", json=payload,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30.0,
    )


async def send_batches_concurrently(base_url: str, api_key: str, batches: list[dict], concurrency: int) -> tuple[float, int, int]:
    """Returns (elapsed_seconds, spans_accepted, error_count)."""
    sem = asyncio.Semaphore(concurrency)
    accepted = 0
    errors = 0

    async with httpx.AsyncClient() as client:
        async def one(payload: dict) -> None:
            nonlocal accepted, errors
            async with sem:
                try:
                    resp = await _post_traces(client, base_url, api_key, payload)
                    if resp.status_code == 200:
                        accepted += resp.json().get("accepted", 0)
                    else:
                        errors += 1
                except httpx.HTTPError:
                    errors += 1

        t0 = time.perf_counter()
        await asyncio.gather(*(one(b) for b in batches))
        elapsed = time.perf_counter() - t0

    return elapsed, accepted, errors


def create_workspace(base_url: str, admin_secret: str, name: str) -> tuple[str, str]:
    resp = httpx.post(
        f"{base_url}/v1/admin/workspaces", json={"name": name},
        headers={"X-Admin-Secret": admin_secret}, timeout=15.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["workspace_id"], data["api_key"]


def login(base_url: str, api_key: str) -> httpx.Client:
    client = httpx.Client(base_url=base_url, timeout=15.0)
    resp = client.post("/v1/auth/login", json={"api_key": api_key})
    resp.raise_for_status()
    return client


# --------------------------------------------------------------------------
# Percentile helpers
# --------------------------------------------------------------------------

def pctl(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * p
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] + (s[c] - s[f]) * (k - f)


def summarize_latencies(label: str, values_s: list[float]) -> dict:
    if not values_s:
        return {"label": label, "n": 0}
    ms = [v * 1000 for v in values_s]
    return {
        "label": label, "n": len(ms),
        "p50_ms": round(pctl(ms, 0.50), 2), "p95_ms": round(pctl(ms, 0.95), 2),
        "p99_ms": round(pctl(ms, 0.99), 2), "max_ms": round(max(ms), 2),
    }


# --------------------------------------------------------------------------
# Celery task-event capture (queue-wait vs. processing time)
# --------------------------------------------------------------------------

class TaskEventCollector:
    """Listens on the Celery event stream for task-sent/-received/-started/
    -succeeded/-failed and keeps per-task-id timestamps, so queue-wait
    (started - sent) and processing time (the worker's own reported
    `runtime`) can be computed after the fact, for exactly the task names
    we care about. Runs in a background thread; Celery's Receiver.capture
    is blocking, so we drive it with a short timeout and re-enter until
    told to stop."""

    WATCHED = {"app.workers.tasks.ingest_spans_batch", "app.workers.tasks.update_graph_and_baselines"}

    def __init__(self) -> None:
        self._tasks: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _on_event(self, event: dict) -> None:
        uuid_ = event.get("uuid")
        if not uuid_:
            return
        etype = event["type"]
        with self._lock:
            entry = self._tasks.setdefault(uuid_, {})
            name = event.get("name")
            if name:
                entry["name"] = name
            if entry.get("name") not in self.WATCHED and etype not in ("task-sent", "task-received"):
                # We may not know the name yet on later events for an
                # unwatched task; harmless to keep writing timestamps,
                # they're just never read for anything but WATCHED names.
                pass
            ts = event.get("timestamp")
            if etype == "task-sent":
                entry["sent"] = ts
            elif etype == "task-received":
                entry.setdefault("sent", ts)
                entry["received"] = ts
            elif etype == "task-started":
                entry["started"] = ts
            elif etype == "task-succeeded":
                entry["succeeded"] = ts
                if "runtime" in event:
                    entry["runtime"] = event["runtime"]
            elif etype == "task-failed":
                entry["failed"] = ts

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                with celery_app.connection() as connection:
                    recv = celery_app.events.Receiver(connection, handlers={
                        "task-sent": self._on_event,
                        "task-received": self._on_event,
                        "task-started": self._on_event,
                        "task-succeeded": self._on_event,
                        "task-failed": self._on_event,
                    })
                    for _ in recv.itercapture(limit=None, timeout=1, wakeup=True):
                        if self._stop.is_set():
                            break
            except Exception:
                if self._stop.is_set():
                    break
                time.sleep(0.5)  # transient broker hiccup -- reconnect

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        time.sleep(0.5)  # let the receiver actually connect before we start dispatching

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def results_for(self, task_name: str) -> dict:
        with self._lock:
            entries = [e for e in self._tasks.values() if e.get("name") == task_name and "succeeded" in e]
        queue_wait = [e["started"] - e["sent"] for e in entries if e.get("started") and e.get("sent")]
        processing = [e["runtime"] for e in entries if e.get("runtime") is not None]
        return {
            "task": task_name,
            "completed": len(entries),
            "queue_wait": summarize_latencies("queue_wait", queue_wait),
            "processing": summarize_latencies("processing", processing),
        }

    def pending_count(self) -> int:
        with self._lock:
            return sum(1 for e in self._tasks.values() if e.get("name") in self.WATCHED and "succeeded" not in e and "failed" not in e)


class QueueDepthSampler:
    """Polls Redis list lengths for the Celery queues directly (Celery's
    Redis broker backs a simple queue with a plain Redis list named after
    the queue) rather than celery_app.control.inspect(), which pings
    workers over the broker and adds its own overhead/latency to the
    thing being measured."""

    def __init__(self, redis_url: str, queues: list[str], interval_s: float = 0.5) -> None:
        import redis as redis_lib
        self._r = redis_lib.from_url(redis_url)
        self._queues = queues
        self._interval = interval_s
        self._samples: list[dict] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._t0 = time.perf_counter()

    def _run(self) -> None:
        while not self._stop.is_set():
            depths = {q: self._r.llen(q) for q in self._queues}
            self._samples.append({"t": round(time.perf_counter() - self._t0, 2), **depths})
            time.sleep(self._interval)

    def start(self) -> None:
        self._t0 = time.perf_counter()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> list[dict]:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        return self._samples

    def summary(self) -> dict:
        out = {}
        for q in self._queues:
            depths = [s[q] for s in self._samples]
            nonzero = [s["t"] for s in self._samples if s[q] > 0]
            out[q] = {
                "max_depth": max(depths) if depths else 0,
                "drain_time_s": round(max(nonzero), 1) if nonzero else 0.0,
            }
        return out


# --------------------------------------------------------------------------
# Benchmark phases
# --------------------------------------------------------------------------

def phase_ingestion_throughput(base_url: str, api_key: str, topo: Topology, args, rng: random.Random) -> list[dict]:
    print("\n=== Phase 1: Ingestion throughput ===")
    results = []
    for concurrency in args.concurrency_levels:
        batches = build_request_batches(topo, args.ingest_total_spans, args.ingest_batch_spans, rng)
        total_spans = sum(count_spans_in_payload(b) for b in batches)
        elapsed, accepted, errors = asyncio.run(send_batches_concurrently(base_url, api_key, batches, concurrency))
        rate = accepted / elapsed if elapsed > 0 else 0.0
        print(f"  concurrency={concurrency:>3}  spans_sent={total_spans:>7}  accepted={accepted:>7}  "
              f"errors={errors:>4}  elapsed={elapsed:6.2f}s  rate={rate:9.1f} spans/sec")
        results.append({
            "concurrency": concurrency, "spans_sent": total_spans, "spans_accepted": accepted,
            "errors": errors, "elapsed_s": round(elapsed, 2), "spans_per_sec": round(rate, 1),
        })
    return results


def phase_queue_and_processing(base_url: str, api_key: str, topo: Topology, args, rng: random.Random,
                                cohort_edge: tuple[str, str], cohort_attr_key: str) -> dict:
    print("\n=== Phase 2: Queue-wait / processing latency / queue depth ===")
    settings = get_settings()

    collector = TaskEventCollector()
    # Celery's broker lives on a different Redis logical DB than the
    # app's own cache/rate-limit usage (CELERY_BROKER_URL vs REDIS_URL --
    # see .env.example) -- sampling REDIS_URL here would silently read
    # an unrelated, always-empty DB and report max_depth=0 no matter how
    # backed up the real queues are.
    sampler = QueueDepthSampler(settings.celery_broker_url, ["ingestion", "graph"], interval_s=0.5)
    collector.start()
    sampler.start()

    batches = build_request_batches(
        topo, args.load_total_spans, args.ingest_batch_spans, rng,
        cohort_edge=cohort_edge, cohort_attr_key=cohort_attr_key,
    )
    total_spans = sum(count_spans_in_payload(b) for b in batches)
    print(f"  firing burst: {total_spans} spans across {len(batches)} requests at concurrency={args.load_concurrency}")
    elapsed, accepted, errors = asyncio.run(send_batches_concurrently(base_url, api_key, batches, args.load_concurrency))
    print(f"  HTTP send done in {elapsed:.2f}s ({accepted} spans accepted, {errors} errors) -- waiting for queue to drain...")

    # Wait for both watched task types to finish processing (queue-wait +
    # processing includes work that happens well after the HTTP responses
    # returned -- ingestion is fire-and-forget from the client's view).
    deadline = time.perf_counter() + args.drain_timeout_s
    while time.perf_counter() < deadline:
        if collector.pending_count() == 0:
            break
        time.sleep(1)
    else:
        print(f"  WARNING: drain timeout ({args.drain_timeout_s}s) hit with {collector.pending_count()} tasks still outstanding")

    time.sleep(1.5)  # let the last few task-succeeded events actually arrive
    depth_summary = sampler.summary()
    samples = sampler.stop()
    collector.stop()

    ingest_result = collector.results_for("app.workers.tasks.ingest_spans_batch")
    graph_result = collector.results_for("app.workers.tasks.update_graph_and_baselines")

    for label, result in [("ingest_spans_batch", ingest_result), ("update_graph_and_baselines", graph_result)]:
        qw, pr = result["queue_wait"], result["processing"]
        print(f"  {label} ({result['completed']} completed):")
        print(f"    queue-wait   p50={qw.get('p50_ms')}ms  p95={qw.get('p95_ms')}ms  p99={qw.get('p99_ms')}ms")
        print(f"    processing   p50={pr.get('p50_ms')}ms  p95={pr.get('p95_ms')}ms  p99={pr.get('p99_ms')}ms")
    for q, s in depth_summary.items():
        print(f"  queue '{q}': max_depth={s['max_depth']}  drained_by_t={s['drain_time_s']}s")

    return {
        "burst_spans": total_spans, "http_send_elapsed_s": round(elapsed, 2),
        "ingest_spans_batch": ingest_result, "update_graph_and_baselines": graph_result,
        "queue_depth_summary": depth_summary, "queue_depth_samples": samples,
    }


def phase_api_latency(base_url: str, api_key: str, args) -> dict:
    print("\n=== Phase 3: API read latency (against accumulated data) ===")
    client = login(base_url, api_key)
    endpoints = ["/v1/bottlenecks", "/v1/services", "/v1/graph", "/v1/incidents"]
    results = {}
    for ep in endpoints:
        latencies = []
        for _ in range(args.api_requests):
            t0 = time.perf_counter()
            resp = client.get(ep)
            latencies.append(time.perf_counter() - t0)
            resp.raise_for_status()
        s = summarize_latencies(ep, latencies)
        print(f"  {ep:<18} n={s['n']:<4} p50={s['p50_ms']}ms  p95={s['p95_ms']}ms  p99={s['p99_ms']}ms  max={s['max_ms']}ms")
        results[ep] = s
    client.close()
    return results


def phase_db_performance(base_url: str, api_key: str, workspace_id: str, cohort_edge: tuple[str, str],
                          cohort_attr_key: str, args) -> dict:
    print("\n=== Phase 4: DB performance (cohort analysis + retention prune) ===")
    client = login(base_url, api_key)

    reg = client.post("/v1/cohort-dimensions", json={"attribute_key": cohort_attr_key, "label": "benchmark cohort"})
    reg.raise_for_status()

    caller, callee = cohort_edge
    latencies = []
    for i in range(args.cohort_requests):
        t0 = time.perf_counter()
        resp = client.get("/v1/cohort-analysis", params={
            "caller": caller, "callee": callee, "dimension": cohort_attr_key, "window_minutes": 1440,
        })
        latencies.append(time.perf_counter() - t0)
        resp.raise_for_status()
        if i == 0:
            print(f"  cohort-analysis cold response: {json.dumps(resp.json())[:200]}")
    cohort_summary = summarize_latencies("cohort-analysis", latencies)
    print(f"  cohort-analysis query: n={cohort_summary['n']} p50={cohort_summary['p50_ms']}ms "
          f"p95={cohort_summary['p95_ms']}ms max={cohort_summary['max_ms']}ms")
    client.close()

    # Retention prune -- run directly in-process against the same DB the
    # api/worker containers use, exactly like the scheduled Celery task
    # does (app/workers/tasks.py calls prune_old_telemetry the same way).
    # older_than_hours=0 deletes everything this workspace has ingested
    # (all of it is "now" -- synthetic data has no real history), which
    # is exactly the point: time a full prune at the row count this
    # benchmark just produced, then leave the workspace clean.
    from app.db.sync_session import SyncSessionLocal
    from app.ingestion.retention import prune_old_telemetry

    with SyncSessionLocal() as db:
        t0 = time.perf_counter()
        prune_result = prune_old_telemetry(db, uuid.UUID(workspace_id), older_than_hours=0)
        elapsed = time.perf_counter() - t0
    print(f"  retention prune: spans_deleted={prune_result['spans_deleted']} "
          f"metrics_deleted={prune_result['metrics_deleted']} elapsed={elapsed:.2f}s")

    return {
        "cohort_analysis": cohort_summary,
        "retention_prune": {**prune_result, "elapsed_s": round(elapsed, 2)},
    }


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url", default="http://localhost:8000")
    p.add_argument("--admin-secret", default=None, help="defaults to GHOST_SECRET_KEY from the environment")
    p.add_argument("--services", type=int, default=50)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--concurrency-levels", default="1,5,10,25,50",
                    help="comma-separated concurrency levels for the ingestion throughput sweep")
    p.add_argument("--ingest-total-spans", type=int, default=20000,
                    help="spans sent per concurrency level in phase 1")
    p.add_argument("--ingest-batch-spans", type=int, default=1000, help="spans per HTTP request")
    p.add_argument("--load-total-spans", type=int, default=100000, help="spans in the phase 2 burst")
    p.add_argument("--load-concurrency", type=int, default=40)
    p.add_argument("--drain-timeout-s", type=int, default=180)
    p.add_argument("--api-requests", type=int, default=100, help="requests per endpoint in phase 3")
    p.add_argument("--cohort-requests", type=int, default=20)
    p.add_argument("--output", default="benchmark_results.json")
    args = p.parse_args()
    args.concurrency_levels = [int(x) for x in args.concurrency_levels.split(",")]
    return args


def main() -> None:
    args = parse_args()
    settings = get_settings()
    admin_secret = args.admin_secret or settings.ghost_secret_key
    if not admin_secret:
        print("ERROR: no admin secret -- pass --admin-secret or set GHOST_SECRET_KEY", file=sys.stderr)
        sys.exit(1)

    rng = random.Random(args.seed)
    topo = build_topology(args.services, args.seed)
    n_edges = len(topo.edges)
    print(f"Topology: {sum(len(l) for l in topo.layers)} services, {n_edges} edges, "
          f"{len(topo.layers)} layers {[len(l) for l in topo.layers]}")

    # Pick a mid-topology edge for the cohort-comparison scenario -- a
    # service-tier -> data-tier edge, closest analogue to a real canary
    # rollout changing something like a cache TTL or a connection-pool size.
    data_edges = [e for e in topo.all_edges if e.caller.startswith("service") and e.callee.startswith("data")]
    cohort_spec = rng.choice(data_edges) if data_edges else rng.choice(topo.all_edges)
    cohort_edge = (cohort_spec.caller, cohort_spec.callee)
    cohort_attr_key = "config.benchmark_cohort_param"
    print(f"Cohort-comparison edge: {cohort_edge[0]} -> {cohort_edge[1]} (attribute: {cohort_attr_key})")

    ws_name = f"benchmark-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}"
    workspace_id, api_key = create_workspace(args.base_url, admin_secret, ws_name)
    print(f"Created workspace {workspace_id} ({ws_name})")

    results: dict = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "topology": {"services": sum(len(l) for l in topo.layers), "edges": n_edges,
                     "layer_sizes": [len(l) for l in topo.layers]},
        "workspace_id": workspace_id,
        "args": vars(args),
    }

    try:
        results["ingestion_throughput"] = phase_ingestion_throughput(args.base_url, api_key, topo, args, rng)
        results["queue_and_processing"] = phase_queue_and_processing(
            args.base_url, api_key, topo, args, rng, cohort_edge, cohort_attr_key,
        )
        results["api_latency"] = phase_api_latency(args.base_url, api_key, args)
        results["db_performance"] = phase_db_performance(
            args.base_url, api_key, workspace_id, cohort_edge, cohort_attr_key, args,
        )
    finally:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\nFull results written to {args.output}")

    print_results_table(results)


def print_results_table(results: dict) -> None:
    print("\n" + "=" * 72)
    print(f"RESULTS  ({results['topology']['services']} services, {results['topology']['edges']} edges)")
    print("=" * 72)

    print("\nIngestion throughput:")
    for r in results["ingestion_throughput"]:
        print(f"  concurrency={r['concurrency']:>3}: {r['spans_per_sec']:>9.1f} spans/sec"
              f"  ({r['spans_accepted']} spans, {r['errors']} errors)")

    qp = results["queue_and_processing"]
    print(f"\nQueue-wait / processing latency (burst of {qp['burst_spans']} spans):")
    for task_key in ("ingest_spans_batch", "update_graph_and_baselines"):
        r = qp[task_key]
        qw, pr = r["queue_wait"], r["processing"]
        print(f"  {task_key}:")
        print(f"    queue-wait : p50={qw.get('p50_ms')}ms p95={qw.get('p95_ms')}ms p99={qw.get('p99_ms')}ms")
        print(f"    processing : p50={pr.get('p50_ms')}ms p95={pr.get('p95_ms')}ms p99={pr.get('p99_ms')}ms")
    for q, s in qp["queue_depth_summary"].items():
        print(f"  queue '{q}' max depth: {s['max_depth']} (drained by t+{s['drain_time_s']}s)")

    print("\nAPI read latency:")
    for ep, s in results["api_latency"].items():
        print(f"  {ep:<18} p50={s['p50_ms']}ms p95={s['p95_ms']}ms p99={s['p99_ms']}ms")

    dbp = results["db_performance"]
    print("\nDB performance:")
    c = dbp["cohort_analysis"]
    print(f"  cohort-analysis query: p50={c['p50_ms']}ms p95={c['p95_ms']}ms max={c['max_ms']}ms")
    rp = dbp["retention_prune"]
    print(f"  retention prune: {rp['spans_deleted']} spans + {rp['metrics_deleted']} metrics "
          f"deleted in {rp['elapsed_s']}s")
    print("=" * 72)


if __name__ == "__main__":
    main()