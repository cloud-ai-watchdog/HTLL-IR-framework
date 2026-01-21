Below is a **comprehensive, practical guide** to **exception handling + failure management in Celery**, with patterns you’ll actually use in production.


## Core failure model

### What Celery guarantees (by default)

* **At-least-once delivery** is possible, but not guaranteed unless you configure ACK behavior.
* Tasks can be:

  * **lost** (ACK early + worker crash mid-task)
  * **duplicated** (ACK late + worker crash after finishing but before ACK)

So reliability is a triangle:

1. **ACK strategy** (when broker considers task “delivered”)
2. **Retries** (what happens on errors)
3. **Idempotency** (safe to run twice)

---

## Task states you’ll see

* `PENDING`: not known to backend yet / not started
* `RECEIVED`: worker got it (events)
* `STARTED`: running (if `task_track_started=True`)
* `RETRY`: scheduled for retry
* `FAILURE`: failed (exception stored)
* `SUCCESS`: finished

---

## 1) Classify failures first (huge practical impact)

### Transient errors (retryable)

* network timeouts, rate limits, temporary DB issues, 503s

### Permanent errors (don’t retry)

* invalid input, schema mismatch, missing file, auth error that won’t change

### Unknown / flaky

* treat as transient but cap retries + alert

**Rule:** You want retries for transient errors, and fast-fail for permanent errors.

---

## 2) “Retry” is the main tool

### A) Manual retry (most explicit, most controllable)

Use `bind=True` so you can call `self.retry()`.

```python
from celery.exceptions import Retry

@app.task(bind=True, max_retries=5, default_retry_delay=10)
def fetch_url(self, url):
    try:
        return http_get(url)  # your code
    except TimeoutError as e:
        raise self.retry(exc=e, countdown=5)   # retry in 5s
```

Notes:

* `self.retry()` raises an internal exception to stop current run
* the task state becomes `RETRY`

### B) Auto-retry (compact)

```python
@app.task(
    bind=True,
    autoretry_for=(TimeoutError, ConnectionError),
    retry_kwargs={"max_retries": 8},
    retry_backoff=True,          # exponential backoff
    retry_backoff_max=300,       # max backoff
    retry_jitter=True,           # jitter avoids thundering herd
)
def call_api(self, payload):
    return third_party_call(payload)
```

Use auto-retry when you have a clean “these exceptions are always transient” list.

---

## 3) Make retries safer (idempotency + dedupe)

Because retries can re-run tasks, assume duplicates can happen.

### Idempotency pattern

Write tasks so “run twice” won’t break:

* Use **unique keys** (task_id or business key) in DB
* Use “upsert” semantics
* Use distributed locks for critical sections (Redis lock, DB row lock)

Example pseudo:

```python
@app.task(bind=True)
def process_order(self, order_id):
    if db.is_processed(order_id):
        return {"status": "already_done"}

    # do work
    db.mark_processed(order_id)
    return {"status": "ok"}
```

---

## 4) ACK strategy: prevent “lost tasks”

### The problem

If broker thinks a task is “handled” too early, a crash can lose work.

### Use late ACK for reliability

```python
@app.task(acks_late=True)
def heavy_job(...):
    ...
```

Or globally:

```python
app.conf.task_acks_late = True
```

### Add this for crash detection

If a worker process is killed, you usually want the message requeued:

```python
app.conf.task_reject_on_worker_lost = True
```

**Typical “reliable” baseline for long tasks:**

```python
app.conf.task_acks_late = True
app.conf.task_reject_on_worker_lost = True
app.conf.worker_prefetch_multiplier = 1
```

Prefetch=1 prevents a worker from hoarding many tasks and then crashing.

---

## 5) Time limits: prevent infinite hangs

### Why

Hung tasks are worse than failed tasks.

```python
app.conf.task_soft_time_limit = 60   # seconds
app.conf.task_time_limit = 70
```

* Soft limit raises `SoftTimeLimitExceeded` (you can catch and cleanup)
* Hard limit kills the task

Example:

```python
from celery.exceptions import SoftTimeLimitExceeded

@app.task(bind=True)
def do_work(self):
    try:
        long_operation()
    except SoftTimeLimitExceeded:
        cleanup_temp_files()
        raise
```

---

## 6) Handling task failures cleanly

### A) Catch & return structured errors (when you don’t want FAILURE state)

Sometimes you want “SUCCESS with error payload” (e.g., batch jobs where failures are expected).

```python
@app.task
def parse_record(x):
    try:
        return {"ok": True, "value": parse(x)}
    except ValueError as e:
        return {"ok": False, "error": str(e)}
```

### B) Raise exceptions (when you want FAILURE state + alerting)

For true failures, let it fail and capture in monitoring.

---

## 7) Callbacks: `link` and `link_error`

### Success callback

```python
sig = main_task.s(args...)
sig.link(on_success.s())
sig.apply_async()
```

Success callback receives the **result** of `main_task`.

### Error callback

```python
sig.link_error(on_fail.s())
```

Error callback receives: `(request, exc, traceback)`.

Example:

```python
@app.task
def on_success(result):
    print("✅ result:", result)

@app.task
def on_fail(request, exc, traceback):
    print("❌ failed:", exc)
```

Use cases:

* notify Slack/Sentry on failure
* cleanup resources on failure
* update DB job record

---

## 8) Groups/chords: failure behavior & strategies

### Group

If one task fails:

* `group_result.get()` will raise (by default)
* or you can do `propagate=False` to collect failures without raising

### Chord (map-reduce)

Chord is sensitive to backend reliability.

Recommended:

* Redis backend
* proper timeouts
* error callbacks

Example safe chord usage:

```python
from celery import chord

job = chord(header_tasks)(reduce_task.s()).on_error(chord_fail.s())
```

Where `chord_fail` can log/alert.

---

## 9) How to not lose errors: logging + monitoring

### A) Log exceptions with context

Include `task_id`, args, business IDs.

```python
import logging
logger = logging.getLogger(__name__)

@app.task(bind=True)
def t(self, x):
    try:
        ...
    except Exception:
        logger.exception("Task failed", extra={"task_id": self.request.id, "x": x})
        raise
```

### B) Use Sentry / OpenTelemetry (recommended)

Celery integrates well with Sentry; you get stack traces + frequency.

---

## 10) Operational failure management

### Worker crashes

* With `acks_late=True` + `reject_on_worker_lost=True`, unfinished tasks are requeued.
* Without it, you may lose in-flight tasks.

### Broker down

* Producers (client) can’t submit tasks
* Workers can’t fetch tasks
* You should handle submit failures in API layer (return 503 / retry submission)

### Backend down (Redis result store)

* tasks may still run (broker ok)
* but `.state/.get()` will fail
* progress tracking won’t work
  Mitigation:
* avoid tight polling
* store results in DB as authoritative output
* treat backend as “nice to have” when possible

---

## 11) Dead-letter / poison messages

Sometimes a task will always fail (bad input) and will keep retrying.

Strategies:

* limit retries: `max_retries`
* route failed tasks to a “dead” queue (manual pattern)
* mark job as failed in DB and stop retrying

Celery itself doesn’t do a classic DLQ automatically for all brokers; you typically implement:

* retry cap
* on_fail callback that writes to a failure store / queue

---

## 12) Recommended “reliable defaults” (good baseline)

```python
app.conf.update(
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,

    task_soft_time_limit=300,
    task_time_limit=330,

    result_expires=3600,   # 1 hour (tune)
)
```

And tasks:

* idempotent
* bounded runtime
* retry only transient exceptions

---

## 13) A complete “production-ish” example task

```python
from celery import Celery
from celery.exceptions import SoftTimeLimitExceeded

app = Celery(...)

class PermanentError(Exception):
    pass

@app.task(
    bind=True,
    acks_late=True,
    autoretry_for=(TimeoutError, ConnectionError),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 8},
)
def ingest(self, record_id: str):
    try:
        rec = db.fetch(record_id)
        if not rec:
            raise PermanentError(f"Record not found: {record_id}")

        if db.already_done(record_id):
            return {"status": "already_done"}

        # do work
        db.mark_done(record_id)
        return {"status": "ok"}

    except PermanentError:
        # no retry: raise failure
        raise

    except SoftTimeLimitExceeded:
        # cleanup if needed
        cleanup(record_id)
        raise
```

---

## Quick decision checklist

If your tasks are **long / expensive**:

* `acks_late=True`
* `prefetch-multiplier=1`
* time limits
* idempotency

If your tasks call flaky external services:

* `autoretry_for` + backoff + jitter
* cap retries and alert on failure

If you need robust progress reporting:

* Redis backend
* `update_state(PROGRESS, meta=...)`

