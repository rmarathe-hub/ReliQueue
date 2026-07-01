# ReliQueue — Week 5 & 6 Plan

**Goal:** Make the repo CI-green, benchmarked, and interview-ready — not bigger, just credible.

**Baseline (start of Week 5):** Weeks 1–4 complete, 440 tests, ownership/validation/claim-ordering hardening done, demo scripts + dashboard + metrics.

**Explicitly not in scope:** Kubernetes, auth/multi-tenant, frontend rewrite, chasing 700+ tests.

---

## Priority map

| Priority | What | Week | Day(s) |
|----------|------|------|--------|
| 1 | Load test + numbers in README | 5 | 32 |
| 2 | `docs/tradeoffs.md` + **Celery/BullMQ comparison table** + parity roadmap | 5 | 34 |
| 3 | README “why” + screenshots + demo GIF | 6 | 37–39 |
| 4 | Deploy to Railway/Fly + live link (optional) | 6 | 41–42 |
| 5 | LinkedIn + pinned GitHub repo | 6 | 43 |

---

# Week 5 — CI, load proof, engineering credibility

**Theme:** “This is a real system, not a toy.”

| Day | Focus | Tasks | Done when |
|-----|--------|--------|-----------|
| **29** | Test suite hygiene | Document `pytest -m "not slow"`, `pytest -m reliability` in README; skim tests for obvious duplicates; ensure markers documented | README test section is recruiter-friendly |
| **30** | Postgres CI prep | Add `.github/workflows/ci.yml`; Postgres service; `TEST_DATABASE_URL`; `alembic upgrade head`; `pytest -m "not slow"` | CI passes on push |
| **31** | GitHub Actions hardening | Add `pytest -m reliability` step; optional manual/scheduled workflow for `pytest -m slow`; CI badge in README | Green badge visible on repo |
| **32** | **Load test (Priority 1)** | `scripts/load_test.py --jobs 500 --workers 5`; report throughput, succeeded/failed/DLQ, duplicate claims, wall time; **Load test results** section in README with real numbers | Resume-ready line: “500 jobs / N workers, 0 duplicate claims, ~X jobs/sec” |
| **33** | Structured logging | JSON-style worker logs: `event`, `worker_id`, `job_id`, `job_type`, `duration_ms`, `status`; example in README | Logs look production-style |
| **34** | **`docs/tradeoffs.md` (Priority 2)** | See **Tradeoffs doc requirements** below | Can answer “why not Celery?” in 60s; table is interview-ready |
| **35** | Docs + README engineering | Link `tradeoffs.md`, `test_matrix.md`; API table current; “Run CI locally” snippet; architecture diagram up to date | README reads like a serious project |
| **36** | Week 5 capstone | `docker compose up` → `demo_run.sh` → load test → `pytest -v`; fix CI/local drift | Week 5 checklist complete |

### Day 34 — `docs/tradeoffs.md` requirements

Include all of the following:

1. **Postgres queue vs Redis vs RabbitMQ** — when each makes sense  
2. **At-least-once vs exactly-once** — what ReliQueue guarantees  
3. **Polling vs push workers** — tradeoffs  
4. **Worker leases** — why they exist  
5. **Idempotency** — why it matters  

6. **Explicit feature comparison table** — ReliQueue vs Celery vs BullMQ (minimum columns):

| Feature | ReliQueue | Celery | BullMQ |
|---------|-----------|--------|--------|
| Durable storage | Postgres | Broker-dependent (Redis/RabbitMQ) | Redis |
| Concurrent claiming | `SKIP LOCKED` | Prefetch / worker model | Redis lists / groups |
| Retries / backoff | ✅ | ✅ | ✅ |
| Dead-letter queue | ✅ | ✅ (varies) | ✅ |
| Job scheduling / `run_at` | ✅ (internal) | ✅ | ✅ |
| Worker leases / crash recovery | ✅ | Partial / broker-dependent | Partial |
| Result backend | ❌ | ✅ | ✅ |
| Task chains / workflows | ❌ | ✅ | ✅ |
| Priority queues | ✅ (basic) | ✅ | ✅ |
| Observability (metrics API) | ✅ | Flower / plugins | Bull Board |
| Language ecosystem | Python API + workers | Python-first | Node-first |

*(Adjust rows to honest current state — mark ❌ where not implemented.)*

7. **“What I’d add next to reach parity”** — ordered roadmap (product thinking), e.g.:

   - Result backend / job output storage  
   - Task chains or DAG-style dependencies  
   - Scheduled/cron jobs (API-exposed `run_at` on create)  
   - Rate limiting per queue  
   - Prometheus metrics export  
   - Separate broker for very high throughput  

   Each item: **one sentence why** it matters and **rough effort** (S/M/L).

8. **When I’d choose ReliQueue vs Celery** — 3-bullet summary (learning, Postgres-only stacks, ops simplicity vs when to use Celery).

### Week 5 suggested commits

1. `add github actions ci with postgres integration tests`
2. `add load test script and document benchmark results`
3. `add structured worker logs`
4. `document queue tradeoffs and celery bullmq comparison`
5. `polish readme for ci load tests and tradeoffs`

### Week 5 done when

- [x] CI green on GitHub  
- [x] README has **real** load test numbers  
- [x] `docs/tradeoffs.md` with **comparison table + parity roadmap**  
- [x] Structured worker logs  
- [x] `pytest` marker commands documented  
- [x] `scripts/capstone.sh` validates full local pipeline  

---

# Week 6 — Portfolio polish & optional deploy

**Theme:** “A recruiter gets it in 30 seconds.”

| Day | Focus | Tasks | Done when |
|-----|--------|--------|-----------|
| **37** | **README “why” (Priority 3)** | Problem statement, what you learned, why Postgres queue; link to `tradeoffs.md` for Celery comparison; 3 bullets “what makes this different” | First screen answers “why exist?” |
| **38** | Screenshots | Dashboard metrics, job detail + timeline, worker health → `docs/screenshots/` or README | 2–3 images in README |
| **39** | Demo GIF / video | 60–90s: `demo_run.sh` → dashboard → failed job → event timeline; optional: 15s mention of tradeoffs table | Visual demo link in README |
| **40** | Interview kit | Resume bullet; 30s pitch; Q&A crib: SKIP LOCKED, retries, leases, **“why not Celery?”** (points to table + parity roadmap) | Can explain without opening code |
| **41** | **Deploy (Priority 4, optional)** | Railway or Fly.io: API + Postgres; migrations; smoke `/health`, `/dashboard` | Public URL in README |
| **42** | Deploy hardening (if 41) | Env docs, `DEBUG=false`, note on running workers locally vs cloud | No secrets leaked |
| **43** | **LinkedIn + GitHub (Priority 5)** | Pin repo; About blurb; post: problem → stack → one metric → link; mention tradeoffs article/table | Repo pinned + one post |
| **44** | Final audit | All checklists; links work; `demo_run.sh` + CI pass | Resume-ready |

### Week 6 interview talking point (Celery)

> “I compared ReliQueue to Celery and BullMQ in `docs/tradeoffs.md`. I intentionally focused on durability, claiming correctness, and leases first. The parity roadmap lists what I’d add next — result backend, workflows, cron — if this were a production system.”

### Week 6 done when

- [ ] README opens with **why** + link to tradeoffs  
- [ ] Screenshots + demo GIF/link  
- [ ] Resume bullet drafted  
- [x] (Optional) Deploy guide + Railway config — [`docs/deploy.md`](deploy.md)  
- [ ] Live demo URL in README (after `railway up`)  
- [ ] Repo pinned + LinkedIn post  
- [x] `scripts/final_audit.sh` — doc links + CI-equivalent tests  
- [ ] Can walk through **comparison table + parity roadmap** in an interview  

---

## Resume bullet (draft)

> **ReliQueue** — Durable Postgres-backed job queue (FastAPI, async workers, `FOR UPDATE SKIP LOCKED`). Retries, dead-letter queue, lease recovery, idempotency; 440+ integration tests, GitHub Actions CI. Load-tested 500 jobs / 5 workers, zero duplicate claims. Documented tradeoffs vs Celery/BullMQ. [GitHub] [Live demo]

---

## 30-second pitch

> “I built a distributed job queue on Postgres to learn how systems like Celery handle crashes and duplicate work without Redis. Workers claim with `SKIP LOCKED`, use leases for recovery, and failed jobs retry or dead-letter. I wrote 440 integration tests, CI on Postgres, and load-tested 500 jobs with no duplicate claims. I also wrote a tradeoffs doc comparing Celery and BullMQ and a roadmap for what I’d add to reach parity.”

---

## Expected strength after Week 5–6

| Metric | Estimate |
|--------|----------|
| Internship score | **8–8.5 / 10** |
| Tier | **Standout** (strong standout with live deploy + good post) |
| Flagship | Needs one external hook (usage, traction, or strong write-up) — not more code |

---

## Deferred (do not block Week 5–6)

- Kubernetes / minikube  
- Auth / multi-tenant  
- Feature parity implementation with Celery (roadmap only in tradeoffs doc)  
- 200+ additional tests  
