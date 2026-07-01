# ReliQueue — Design Tradeoffs

Why build a Postgres-backed queue instead of reaching for Celery or BullMQ? This document captures the engineering choices behind ReliQueue, what it guarantees today, and what would be needed to reach feature parity with mature task queues.

**Audience:** interview prep, design reviews, and anyone asking “why not just use Celery?”

---

## 1. Postgres queue vs Redis vs RabbitMQ

| Store | Strengths | Weaknesses | When it fits |
|-------|-----------|------------|--------------|
| **Postgres (ReliQueue)** | ACID transactions, one database for app + queue, `FOR UPDATE SKIP LOCKED`, strong durability, familiar ops | Polling adds latency vs in-memory brokers; throughput ceiling lower than Redis for firehose workloads | Small–medium throughput, teams already on Postgres, want transactional job state beside business data |
| **Redis** | Very fast, native list/stream primitives, great for high-volume ephemeral work | Durability depends on AOF/RDB settings; job state often separate from primary DB; memory-bound | High throughput, short tasks, already running Redis at scale |
| **RabbitMQ** | Mature AMQP routing, push delivery, exchanges/queues/bindings | Extra moving part, different operational model, less natural fit if you only need a simple work queue | Complex routing, pub/sub patterns, polyglot consumers, dedicated messaging team |

ReliQueue bets on **operational simplicity**: if your product already depends on Postgres, a queue in the same database avoids another failure domain and lets you reason about jobs with normal SQL.

---

## 2. At-least-once vs exactly-once

**ReliQueue provides at-least-once execution.**

A job may be delivered more than once when:

- A worker crashes after running the handler but before marking success.
- A lease expires and another worker reclaims the job while the first is still running (slow handler + short lease).
- A retry is scheduled after a transient failure.

ReliQueue does **not** guarantee exactly-once. Duplicate claims of the *same attempt* are prevented by `SKIP LOCKED` and transactional claim updates — load tests and concurrency tests assert zero duplicate `job_claimed` events per attempt. But the **handler** may still run twice across attempts or after crash recovery.

**Implication:** handlers should be **idempotent** or guarded with external deduplication (DB unique constraints, idempotency keys on side effects).

Exactly-once end-to-end usually requires distributed transactions or a separate idempotency store — out of scope for this learning project.

---

## 3. Polling vs push workers

| | Polling (ReliQueue) | Push (RabbitMQ / some Redis patterns) |
|--|---------------------|----------------------------------------|
| **Mechanism** | Workers `SELECT … FOR UPDATE SKIP LOCKED` on an interval | Broker delivers message to consumer |
| **Latency** | Bounded by `poll_interval` (default 2s) | Often lower — message pushed immediately |
| **Load on broker/DB** | Steady read load even when idle | Idle workers are quiet |
| **Simplicity** | No broker protocol; just SQL + HTTP API | Requires connection management, ack/nack semantics |
| **Backpressure** | Natural — workers only claim what they can run | Depends on prefetch / consumer ack model |

ReliQueue uses **polling** deliberately: fewer concepts for a portfolio queue, works through firewalls, and pairs cleanly with Postgres row locks. Tradeoff: sub-second latency requires aggressive poll intervals (see load test ~9 jobs/sec with 5 workers — throughput scales with workers and handler duration, not push fanout).

---

## 4. Worker leases — why they exist

When a worker claims a job it sets:

- `locked_by` — which worker owns the attempt  
- `locked_at` — when the claim happened  
- `lease_expires_at` — deadline before the job is considered abandoned  

**Problem without leases:** a worker dies mid-job; the row stays `running` forever.

**Solution:** `recover_expired_leases` scans for `running` jobs whose lease has passed and returns them to `pending`. Another worker can reclaim and retry.

Leases are a **crash-recovery** mechanism, not a distributed lock for long critical sections. Handlers should finish within `WORKER_LEASE_SECONDS` (default 60s) or the job may be double-processed after recovery.

---

## 5. Idempotency — why it matters

The API accepts an optional **`idempotency_key`** on job creation:

| Case | Response |
|------|----------|
| New key | `201 Created` |
| Same key + same payload | `200 OK` (existing job) |
| Same key + different payload | `409 Conflict` |

This protects **submitters** from duplicate enqueues (network retries, double-clicks). It does **not** make handlers idempotent — two different jobs can still perform the same side effect if you do not design for it.

At-least-once delivery + idempotent handlers is the standard production pattern ReliQueue is built to teach.

---

## 6. Feature comparison — ReliQueue vs Celery vs BullMQ

Honest snapshot of **ReliQueue today** (Week 5) against two widely used queues.

| Feature | ReliQueue | Celery | BullMQ |
|---------|-----------|--------|--------|
| Durable storage | Postgres | Broker-dependent (Redis/RabbitMQ/etc.) | Redis |
| Concurrent claiming | `FOR UPDATE SKIP LOCKED` | Prefetch / worker concurrency model | Redis lists / consumer groups |
| Retries / backoff | ✅ exponential + jitter | ✅ | ✅ |
| Dead-letter queue | ✅ `dead_lettered` status + API | ✅ (varies by config) | ✅ |
| Job scheduling / `run_at` | ✅ internal (retry backoff); ❌ not on create API | ✅ ETA/countdown/cron | ✅ delayed jobs |
| Worker leases / crash recovery | ✅ lease + recovery loop | Partial / broker-dependent | Partial (stall detection) |
| Result backend | ❌ | ✅ | ✅ |
| Task chains / workflows | ❌ | ✅ chords, groups, chains | ✅ flows |
| Priority queues | ✅ basic (`priority` on create) | ✅ | ✅ |
| Observability | ✅ `/api/metrics` + HTML dashboard | Flower / plugins | Bull Board |
| Structured worker logs | ✅ JSON per line | Varies | Varies |
| Language ecosystem | Python API + workers | Python-first | Node-first |

**Load test reference (local Docker):** 500 jobs / 5 workers, **0 duplicate claims**, ~**9 jobs/sec** — see README Load test section.

---

## 7. What I’d add next to reach parity

Ordered roadmap — each item is one step toward Celery/BullMQ-class ergonomics without rewriting the core.

| # | Feature | Why it matters | Effort |
|---|---------|----------------|--------|
| 1 | **Result backend / job output storage** | Callers need task output without scraping logs or custom tables | **M** — new `job_results` table, API on complete, retention policy |
| 2 | **Task chains / DAG dependencies** | “Run B after A succeeds” is the most requested workflow primitive | **L** — dependency graph, blocked-until-ready claiming, cycle detection |
| 3 | **API-exposed `run_at` on create** | Schedule work for the future (cron replacement, delayed sends) without hacks | **S** — extend `JobCreate`, validation, claim filter already respects `run_at` |
| 4 | **Rate limiting per queue** | Protect downstream APIs and smooth spikes | **M** — token bucket per queue, worker-side or claim-time throttle |
| 5 | **Prometheus metrics export** | `/api/metrics` is demo-friendly; Prometheus is production-standard scraping | **S** — `prometheus_client` counters/histograms, `/metrics` route |
| 6 | **Separate broker for very high throughput** | Postgres polling tops out; Redis/RabbitMQ layer for fanout while keeping Postgres as source of truth is a common hybrid | **L** — dual-write or outbox pattern, new ops surface |

---

## 8. When I’d choose ReliQueue vs Celery

**Choose ReliQueue when:**

- You want to **learn** how distributed queues work — claims, leases, retries, DLQ — without Celery’s abstraction layer.
- Your stack is **Postgres-first** and you want one datastore for app data and durable jobs.
- You need a **small, inspectable** system with a REST API, dashboard, CI, and tests you can explain in an interview.

**Choose Celery (or BullMQ in Node) when:**

- You need **task chains, chords, cron**, or a **result backend** on day one.
- Throughput is **high** and Redis/RabbitMQ is already standard in your org.
- You want a **battle-tested ecosystem** (Flower, monitoring plugins, years of production patterns) over a teaching implementation.

**One-line pitch:** ReliQueue is a deliberate **Postgres `SKIP LOCKED` queue** for learning and modest workloads; Celery is the right default for most production Python task farms.

---

## Related docs

- [README](../README.md) — setup, API, load test numbers  
- [test_matrix.md](./test_matrix.md) — what the 458 tests cover  
- [week5-week6-plan.md](./week5-week6-plan.md) — portfolio roadmap  
