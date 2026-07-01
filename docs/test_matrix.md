# ReliQueue Test Coverage Matrix

Last updated: Week 5 Day 31 (440 tests).

This matrix maps behavior areas to tests, gaps addressed in the latest expansion, and remaining risk. Priority: **critical**, **important**, **nice-to-have**.

---

## Running tests

| Command | Count | Purpose |
|---------|-------|---------|
| `pytest -v` | 440 | Full local validation |
| `pytest -m "not slow" -v` | 436 | CI / fast feedback (excludes stress tests) |
| `pytest -m reliability -v` | 7 | Core reliability slice (`test_reliability.py`) |
| `pytest -m slow -v` | 3 | Concurrency stress only |

**Prerequisites:** Postgres running; `TEST_DATABASE_URL` pointing at `reliqueue_test` (see README).

### Pytest markers

| Marker | Scope |
|--------|--------|
| `reliability` | Retries, backoff, manual retry, cancel, lease recovery, DLQ event timelines |
| `slow` | Large-batch concurrency (`test_concurrency.py`, `test_concurrency_extended.py`) |

### Intentional overlap

Some behaviors are covered in more than one file on purpose:

| Area | Files | Why |
|------|-------|-----|
| State machine guards | `test_job_state_machine.py`, `test_state_machine_extended.py` | Core transitions vs additional invalid-transition edge cases |
| Worker ownership | `test_job_state_machine.py`, `test_ownership_guards.py` | State machine context vs focused lock/ownership regression suite |
| Demo scripts | `test_demo_scripts.py`, `test_demo_scripts_extended.py`, `test_demo_script_regressions.py` | Helper unit tests, extended coverage, README/shell regressions |
| Dashboard | `test_dashboard.py`, `test_dashboard_extended.py`, `test_dashboard_security.py` | Smoke, UI sections, security/static-file checks |

---

## Summary

| Metric | Value |
|--------|-------|
| **Total tests** | 440 |
| **Reliability (`-m reliability`)** | 7 |
| **Slow (`-m slow`)** | 3 |
| **Full suite runtime** | ~30s |
| **Not-slow runtime** | ~30s |

---

## 1. Health endpoint

| Item | Detail |
|------|--------|
| **Existing tests** | `test_health.py`, `test_health_extended.py` |
| **Coverage** | DB-connected 200, response shape, JSON serializable, no secret leakage |
| **New tests added** | `test_health_extended.py` (4) |
| **Remaining risk** | Unhealthy DB path not mocked |
| **Priority** | nice-to-have |

---

## 2. Job creation API

| Item | Detail |
|------|--------|
| **Existing tests** | `test_jobs_api.py`, `test_jobs_api_validation.py`, `test_jobs_api_detail.py` |
| **Coverage** | Valid create, defaults, payload variants, max_attempts bounds, priority, queue_name, field presence, list-after-create |
| **New tests added** | `test_jobs_api_detail.py` — response fields, max_attempts=1 |
| **Remaining risk** | Low |
| **Priority** | critical — covered |

---

## 3. Idempotency

| Item | Detail |
|------|--------|
| **Existing tests** | `test_jobs_api.py`, `test_jobs_api_idempotency.py`, E2E |
| **Coverage** | 200 replay, 409 conflict, single job_created event, conflict dimensions |
| **New tests added** | — |
| **Remaining risk** | Low |
| **Priority** | critical — covered |

---

## 4. Job listing / filtering / pagination

| Item | Detail |
|------|--------|
| **Existing tests** | `test_jobs_api_listing.py` |
| **Coverage** | Status/queue/type filters, combined filters, limit/offset, empty, ordering, pagination disjoint pages |
| **New tests added** | — |
| **Remaining risk** | Low |
| **Priority** | important — covered |

---

## 5. Job detail API

| Item | Detail |
|------|--------|
| **Existing tests** | `test_jobs_api.py`, `test_jobs_api_detail.py` |
| **Coverage** | All statuses, lock fields when running, last_error when DL, completed_at when succeeded, 404 |
| **New tests added** | `test_jobs_api_detail.py` (8) |
| **Remaining risk** | Low |
| **Priority** | important — covered |

---

## 6. Job event timeline API

| Item | Detail |
|------|--------|
| **Existing tests** | `test_job_events.py`, `test_jobs_api.py` |
| **Coverage** | Chronological order, metadata per event type, cancel/retry/lease events |
| **New tests added** | Mutation API event checks in `test_jobs_api_mutations.py` |
| **Remaining risk** | Low |
| **Priority** | important — covered |

---

## 7. API validation / errors

| Item | Detail |
|------|--------|
| **Existing tests** | `test_jobs_api_validation.py` |
| **Coverage** | 422 for invalid create/list/worker params, invalid UUIDs on all mutation routes |
| **New tests added** | — |
| **Remaining risk** | Low |
| **Priority** | critical — covered |

---

## 8. Worker registration

| Item | Detail |
|------|--------|
| **Existing tests** | `test_workers_api.py`, `test_workers_api_extended.py` |
| **Coverage** | Register online, idempotent re-register, queue_name stored |
| **New tests added** | `test_workers_api_extended.py` — idempotent register |
| **Remaining risk** | Low |
| **Priority** | important — covered |

---

## 9. Worker heartbeat

| Item | Detail |
|------|--------|
| **Existing tests** | `test_workers_api.py`, `test_workers_api_extended.py` |
| **Coverage** | Timestamp updates, preserves current_job_id |
| **New tests added** | `test_workers_api_extended.py` |
| **Remaining risk** | Low |
| **Priority** | important — covered |

---

## 10. Worker list / detail APIs

| Item | Detail |
|------|--------|
| **Existing tests** | `test_workers_api.py`, `test_workers_extended.py`, `test_workers_api_extended.py` |
| **Coverage** | Empty list, pagination, filters, shape, current_job_id, 404 |
| **New tests added** | `test_workers_api_extended.py` (8) |
| **Remaining risk** | Low |
| **Priority** | important — covered |

---

## 11. Worker handler behavior

| Item | Detail |
|------|--------|
| **Existing tests** | `test_worker_handlers.py` (10) |
| **Coverage** | All demo handlers |
| **New tests added** | — |
| **Remaining risk** | Demo handlers only |
| **Priority** | nice-to-have |

---

## 12. Safe job claiming

| Item | Detail |
|------|--------|
| **Existing tests** | `test_worker_claiming.py`, `test_service_claiming_extended.py`, `test_concurrency.py` |
| **Coverage** | SKIP LOCKED, skip statuses, lease fields, worker current_job_id, unrelated jobs, wrong queue |
| **New tests added** | `test_service_claiming_extended.py` (6) |
| **Remaining risk** | Low |
| **Priority** | critical — covered |

---

## 13. Claim ordering

| Item | Detail |
|------|--------|
| **Existing tests** | `test_worker_claiming.py` |
| **Coverage** | priority DESC, run_at ASC |
| **New tests added** | — |
| **Remaining risk** | No `created_at` tie-breaker |
| **Priority** | nice-to-have |

---

## 14. Queue isolation

| Item | Detail |
|------|--------|
| **Existing tests** | `test_worker_claiming.py`, `test_concurrency.py`, E2E |
| **Coverage** | Workers only claim their queue |
| **New tests added** | `test_service_claiming_extended.py` |
| **Remaining risk** | Low |
| **Priority** | critical — covered |

---

## 15. Multi-worker concurrency

| Item | Detail |
|------|--------|
| **Existing tests** | `test_concurrency.py` (5, 1 slow) |
| **Coverage** | 30/60 jobs, 100 jobs/10 workers, multi-queue, two-worker same job |
| **New tests added** | — |
| **Remaining risk** | Low |
| **Priority** | critical — covered |

---

## 16. Success completion

| Item | Detail |
|------|--------|
| **Existing tests** | `test_worker_execution.py`, `test_worker_completion_extended.py` |
| **Coverage** | Owning worker, wrong worker, double success, terminal statuses, worker clear |
| **New tests added** | State machine: running without lock can complete (documented) |
| **Remaining risk** | Null `locked_by` allows any worker to complete |
| **Priority** | important — documented |

---

## 17–23. Failure, retry, DLQ, manual retry, cancel, lease recovery

| Area | Tests | New files |
|------|-------|-----------|
| Failure handling | `test_worker_failure.py`, `test_worker_failure_extended.py` | — |
| Retry policy | `test_retry_policy.py` (11) | — |
| Manual retry | `test_job_manual_retry.py`, `test_jobs_api_mutations.py` | API retry matrix |
| Cancellation | `test_job_cancellation.py`, `test_jobs_api_mutations.py` | API cancel matrix |
| Lease recovery | `test_job_lease_recovery.py`, `test_lease_recovery_extended.py` | +5 extended |
| State machine | `test_job_state_machine.py` (21) | +3 transitions |

---

## 24–26. Events, E2E, lifecycle

| Item | Detail |
|------|--------|
| **Existing tests** | `test_job_events.py`, `test_e2e_queue_lifecycle.py` (13) |
| **New tests added** | Metrics-after-lifecycle, dashboard-after-seed, cancel→retry→claim E2E |
| **Remaining risk** | Low |
| **Priority** | important — covered |

---

## 27–28. Metrics API and edge cases

| Item | Detail |
|------|--------|
| **Existing tests** | `test_metrics_api.py`, `test_metrics_readiness.py`, `test_metrics_extended.py` |
| **Coverage** | Empty DB, seeded dataset, queue_depth rules, time windows, avg runtime, bulk jobs, read-only, schema keys |
| **New tests added** | `test_metrics_extended.py` (22) |
| **Remaining risk** | Low |
| **Priority** | critical — covered |

---

## 29–30. Dashboard route and static content

| Item | Detail |
|------|--------|
| **Existing tests** | `test_dashboard.py`, `test_dashboard_extended.py` |
| **Coverage** | HTML 200, API polls, job/worker detail UI, refresh, no secrets/paths, static file parity |
| **New tests added** | `test_dashboard_extended.py` (13) |
| **Remaining risk** | No browser/E2E JS execution tests |
| **Priority** | important — covered |

---

## 31–32. Demo scripts and failure handling

| Item | Detail |
|------|--------|
| **Existing tests** | `test_demo_scripts.py`, `test_demo_scripts_extended.py`, `test_demo_script_regressions.py` |
| **Coverage** | Profiles, payloads, verify_claims duplicate detection, shell script executable, README alignment |
| **New tests added** | `test_demo_scripts_extended.py` (16) |
| **Remaining risk** | `demo_run.sh` not executed in CI (Docker required) |
| **Priority** | important — helpers covered |

---

## 33–36. Load-test, CI, logging, README readiness

| Area | Status |
|------|--------|
| **Load-test readiness** | Concurrency + metrics bulk tests; no `load_test.py` yet |
| **CI readiness** | `test_ci_readiness.py` — markers, collect, migrations, `ci.yml` + `slow-tests.yml` workflows |
| **Structured logging** | Not implemented (Week 5) |
| **README accuracy** | Checked in demo script tests |

---

## Target suite size

| Phase | Count |
|-------|-------|
| Week 3 audit baseline | 101 |
| Pre–Week 4 expansion | 231 |
| Post–Week 4 | 248 |
| **Pre–Week 5 hardening** | 440 |
| **Week 5 Day 29 hygiene** | 438 |
| **Week 5 Day 30 CI** | 439 |
| **Week 5 Day 31 CI hardening** | **440** |

No shallow inflation — parametrized tests cover real API/service behaviors only.
