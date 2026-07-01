# ReliQueue Test Coverage Matrix

Last updated: Week 3 expansion (pre–Week 4 metrics).

**Post-expansion status:** 231 tests passing (130 new since 101-test audit baseline).

This matrix maps major behavior areas to existing tests, gaps, and planned coverage. Priority levels: **critical**, **important**, **nice-to-have**.

---

## 1. Health / API foundation

| Item | Coverage |
|------|----------|
| **Current tests** | `test_health.py` (DB-connected health) |
| **Missing edge cases** | Health when DB down (dev-only 503 body) |
| **Suggested new tests** | Optional unhealthy DB mock |
| **Priority** | nice-to-have |

---

## 2. Job creation

| Item | Coverage |
|------|----------|
| **Current tests** | `test_jobs_api.py::test_create_job`, validation error for `max_attempts=0` |
| **Missing edge cases** | Missing job_type, empty job_type, empty payload default, queue_name default, future run_at, priority bounds, max_attempts upper bound |
| **Suggested new tests** | `test_jobs_api_validation.py` — parametrized 422 cases, defaults, empty payload |
| **Priority** | critical |

---

## 3. Idempotency

| Item | Coverage |
|------|----------|
| **Current tests** | Same key+payload 200, payload conflict 409, single job_created event (E2E) |
| **Missing edge cases** | Conflicts on job_type, queue_name, max_attempts, priority; no key → separate jobs; DB unique constraint |
| **Suggested new tests** | `test_jobs_api_idempotency.py` — parametrized conflict dimensions, race-safe duplicate |
| **Priority** | critical |

---

## 4. Job listing / filtering / pagination

| Item | Coverage |
|------|----------|
| **Current tests** | Basic list with status+job_type; invalid status 422 |
| **Missing edge cases** | Each status filter, queue_name, combined filters, limit/offset, empty results, default order (`created_at DESC`), limit cap 100, offset 0 edge |
| **Suggested new tests** | `test_jobs_api_listing.py` |
| **Priority** | important |

---

## 5. Job detail / events

| Item | Coverage |
|------|----------|
| **Current tests** | Detail 200/404, events 404, invalid UUID 422, job_created on create |
| **Missing edge cases** | Event chronological order, metadata per event type, retry/cancel invalid UUID |
| **Suggested new tests** | `test_job_events.py` |
| **Priority** | important |

---

## 6. API validation / errors

| Item | Coverage |
|------|----------|
| **Current tests** | Partial (max_attempts, invalid UUID, invalid status) |
| **Missing edge cases** | limit=0, limit=101, offset=-1, empty queue_name, retry/cancel invalid UUID |
| **Suggested new tests** | `test_jobs_api_validation.py`, API routes for retry/cancel |
| **Priority** | critical |

---

## 7. Worker registration / heartbeat

| Item | Coverage |
|------|----------|
| **Current tests** | Register, heartbeat timestamp, list/detail API, status+queue filter |
| **Missing edge cases** | Duplicate register safe, list pagination API, invalid worker status filter, current_job_id on detail after claim |
| **Suggested new tests** | `test_workers_extended.py` |
| **Priority** | important |

**Note:** `touch_worker_heartbeat` does not set `current_job_id`; only claim/completion/failure/recovery do.

---

## 8. Handler behavior

| Item | Coverage |
|------|----------|
| **Current tests** | `test_worker_handlers.py` (10 tests — all demo handlers) |
| **Missing edge cases** | Minimal — handlers are demo-only |
| **Suggested new tests** | None required pre–Week 4 |
| **Priority** | nice-to-have |

---

## 9. Job claiming

| Item | Coverage |
|------|----------|
| **Current tests** | `test_worker_claiming.py` (14 tests) — empty queue, running state, events, skip statuses, priority, run_at, queue isolation, lease, current_job_id |
| **Missing edge cases** | Unrelated jobs unchanged after claim; same priority+run_at ordering undocumented |
| **Suggested new tests** | `test_worker_claiming.py` — isolation of unrelated jobs |
| **Priority** | important |

---

## 10. Priority / run_at / queue ordering

| Item | Coverage |
|------|----------|
| **Current tests** | priority DESC, run_at ASC, queue_name isolation |
| **Missing edge cases** | No `created_at` tie-breaker (DB order undefined for ties) |
| **Suggested new tests** | Document-only test or comment in matrix; no product change |
| **Priority** | nice-to-have |

---

## 11. Concurrency

| Item | Coverage |
|------|----------|
| **Current tests** | 30 jobs / 5 workers, no duplicates |
| **Missing edge cases** | 100 jobs / 10 workers; mixed future/cancelled under load; multi-queue concurrent claim |
| **Suggested new tests** | `test_concurrency.py` (`@pytest.mark.slow` for 100-job case) |
| **Priority** | critical |

---

## 12. Success completion

| Item | Coverage |
|------|----------|
| **Current tests** | Updates job, event, wrong worker, double success, pending ignored |
| **Missing edge cases** | cancelled/dead_lettered cannot complete; worker current_job_id cleared; unrelated jobs/workers unchanged |
| **Suggested new tests** | `test_worker_completion_extended.py` |
| **Priority** | critical |

---

## 13. Failure handling

| Item | Coverage |
|------|----------|
| **Current tests** | Retry schedule, dead-letter, events, wrong worker, fail_always/fail_once, no retry_scheduled on DL |
| **Missing edge cases** | Cannot fail pending/succeeded/cancelled/dead_lettered; unrelated jobs unchanged |
| **Suggested new tests** | `test_worker_failure_extended.py` |
| **Priority** | critical |

---

## 14. Retry policy

| Item | Coverage |
|------|----------|
| **Current tests** | Exponential, cap, jitter bounds, run_at |
| **Missing edge cases** | attempt 1/2/3 explicit; config from settings; delay never negative; jitter max bound |
| **Suggested new tests** | Extend `test_retry_policy.py` |
| **Priority** | important |

---

## 15. Retry scheduling

| Item | Coverage |
|------|----------|
| **Current tests** | Via failure service + reliability tests |
| **Missing edge cases** | Future run_at blocks claim until eligible |
| **Suggested new tests** | Covered in failure + claiming tests |
| **Priority** | important (covered) |

---

## 16. Dead-letter behavior

| Item | Coverage |
|------|----------|
| **Current tests** | max_attempts, fail_always E2E, manual retry from DL |
| **Missing edge cases** | DL keeps last_error; not claimable; not cancellable |
| **Suggested new tests** | cancellation + claiming tests |
| **Priority** | important (mostly covered) |

---

## 17. Manual retry

| Item | Coverage |
|------|----------|
| **Current tests** | DL + cancelled service tests; API 409/404 for pending/running/succeeded |
| **Missing edge cases** | invalid UUID 422; appears in pending list filter |
| **Suggested new tests** | Extend `test_job_manual_retry.py` |
| **Priority** | important |

---

## 18. Cancellation

| Item | Coverage |
|------|----------|
| **Current tests** | pending, running 409, not claimed, DL/already-cancelled service, API |
| **Missing edge cases** | succeeded/dead_lettered via API; invalid UUID; cancelled list filter |
| **Suggested new tests** | Extend `test_job_cancellation.py` |
| **Priority** | important |

---

## 19. Lease recovery

| Item | Coverage |
|------|----------|
| **Current tests** | 8 tests — recover, event, worker clear, skip active, reclaim, skip pending/succeeded, preserve attempts |
| **Missing edge cases** | skip cancelled/dead_lettered; repeated recovery idempotent; multi-queue; empty recovery safe |
| **Suggested new tests** | Extend `test_job_lease_recovery.py` |
| **Priority** | critical |

---

## 20. Event timeline ordering

| Item | Coverage |
|------|----------|
| **Current tests** | E2E success, reliability timeline, partial event metadata |
| **Missing edge cases** | Full metadata validation per event type; strict chronological API response |
| **Suggested new tests** | `test_job_events.py`, expand E2E |
| **Priority** | important |

---

## 21. Worker ownership checks

| Item | Coverage |
|------|----------|
| **Current tests** | Wrong worker on success/failure |
| **Missing edge cases** | Ownership on all mutation paths |
| **Suggested new tests** | state machine + completion/failure extended |
| **Priority** | critical (covered after audit fix) |

---

## 22. E2E lifecycle behavior

| Item | Coverage |
|------|----------|
| **Current tests** | `test_e2e_queue_lifecycle.py` (7 tests) |
| **Missing edge cases** | API failure→retry path; cancel lifecycle; retry-then-success order |
| **Suggested new tests** | Expand E2E file |
| **Priority** | important |

---

## 23. Docker / dev setup assumptions

| Item | Coverage |
|------|----------|
| **Current tests** | Manual audit (compose up, alembic, health curl) |
| **Missing edge cases** | Not automated in pytest (intentional) |
| **Suggested new tests** | None in unit suite |
| **Priority** | nice-to-have |

---

## 24. Metrics readiness

| Item | Coverage |
|------|----------|
| **Current tests** | Schema has status, timestamps, events indexed |
| **Missing edge cases** | Fixture seeding all statuses + time windows |
| **Suggested new tests** | `test_metrics_readiness.py` + `helpers.seed_metrics_dataset` |
| **Priority** | important (pre–Day 22) |

---

## Summary by priority

| Priority | Areas |
|----------|-------|
| **critical** | Job creation validation, idempotency, concurrency, success/failure guards, lease recovery gaps, state machine |
| **important** | Listing/pagination, events, workers extended, retry policy, manual retry/cancel API, E2E, metrics fixtures |
| **nice-to-have** | Health DB-down, handler extras, created_at tie-breaker, Docker automation |

## Target suite size

- **Baseline:** 101 tests (post–Week 3 audit)
- **Target:** 200–300 meaningful tests
- **Not targeting:** 700+ shallow tests
