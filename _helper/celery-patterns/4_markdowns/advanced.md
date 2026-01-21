Below is a **mini documentation-style guide** you can keep as a reference, with **concepts + when to use + examples**.

I’ll assume:

* broker: RabbitMQ or Redis
* backend: Redis (recommended for advanced workflows)

---

# 📘 Advanced Celery Concepts — Practical Guide

## 0. Mental Model (very important)

Celery = **distributed function execution engine**

* **Task** = unit of work
* **Broker** = task queue (who should work)
* **Worker slots** = parallel execution capacity
* **Backend** = where results + states are stored

Celery does NOT parallelize inside one task.
Parallelism happens only when you create **many tasks**.

---

# 1. Task Signatures (`.s`, `.si`)

### What is a signature?

A **task call description**, not execution.

```python
sig = task.s(10)
```

Nothing runs yet.

### Why needed?

Used to build workflows like chains, groups, chords.

### `.s()` vs `.si()`

```python
task.s(10)   # mutable — receives previous task result
task.si(10)  # immutable — ignores previous result
```

Used in chains.

---

# 2. Chain — Sequential Pipelines

### Use when:

Output of one task is input to next.

### Example

```python
from celery import chain

chain(
    load_data.s(),
    preprocess.s(),
    train_model.s(),
    evaluate.s()
)()
```

Flow:

```
load_data → preprocess → train_model → evaluate
```

Each runs on workers, not locally.

---

# 3. Group — Parallel Map

### Use when:

Same operation on many independent inputs.

### Example

```python
from celery import group

jobs = group(process_chunk.s(c) for c in chunks)
res = jobs.apply_async()

results = res.get()
```

All `process_chunk()` run in parallel.

---

# 4. Chord — Map → Reduce (Fan-out → Fan-in)

### Use when:

Parallel compute + final aggregation.

### Example: sum of squares

```python
from celery import chord

job = chord(
    map_sq_sum.s(c) for c in chunks
)(
    reduce_sum.s()
)

final = job.get()
```

Flow:

```
map tasks run in parallel
        ↓
reduce task runs once with list of results
```

### Requirements

* Needs **result backend** (Redis preferred)

---

# 5. Routing & Queues

### Use when:

Different types of workers handle different workloads.

Example:

* GPU workers
* CPU workers
* IO workers

### Define task routing

```python
celery_app.conf.task_routes = {
    "tasks.train_model": {"queue": "gpu"},
    "tasks.fetch_data": {"queue": "io"},
}
```

### Start workers

```bash
celery -A app worker -Q gpu --concurrency 2
celery -A app worker -Q io --concurrency 10
```

Broker distributes tasks by queue.

---

# 6. Retries

### Use when:

Transient failures (network, API, DB).

### Automatic retry

```python
@app.task(bind=True, autoretry_for=(Exception,), retry_kwargs={"max_retries": 5, "countdown": 10})
def fetch_url(self, url):
    return requests.get(url).text
```

### Manual retry

```python
@app.task(bind=True)
def fragile(self):
    try:
        ...
    except Exception as e:
        raise self.retry(exc=e, countdown=5)
```

---

# 7. Countdown & ETA (Scheduling)

### Delay execution

```python
task.apply_async(args=(10,), countdown=30)  # after 30 sec
```

### Schedule at time

```python
task.apply_async(eta=datetime.utcnow() + timedelta(minutes=10))
```

Used for:

* retries
* deferred jobs

---

# 8. Rate Limiting

### Use when:

Protect APIs / DB / GPUs.

```python
@app.task(rate_limit="5/m")
def send_email():
    ...
```

Worker enforces it, not broker.

---

# 9. Task Acknowledgement & Reliability

### Default:

Task acknowledged AFTER execution.

### If worker crashes mid-task:

Task is re-queued.

### Late ack (safer)

```python
@app.task(acks_late=True)
def critical_job():
    ...
```

Ensures no silent loss of tasks.

---

# 10. Prefetch Control (important for fairness)

### Problem:

Workers may grab too many tasks and block others.

### Fix:

```bash
celery worker --prefetch-multiplier=1
```

Each worker only holds one task per slot.

Critical for:

* long-running tasks
* heterogeneous job durations

---

# 11. Progress Tracking (Custom States)

### Use when:

Long tasks, want % progress.

```python
@app.task(bind=True)
def long_job(self, n):
    for i in range(n):
        self.update_state(state="PROGRESS", meta={"done": i, "total": n})
        time.sleep(1)
    return "done"
```

Client:

```python
r = long_job.delay(100)
print(r.state, r.info)
```

---

# 12. Error Handling & Callbacks

### Success callback

```python
task.s().link(on_success.s())
```

### Error callback

```python
task.s().link_error(on_fail.s())
```

Used in workflows.

---

# 13. Canvas Primitives Summary

| Primitive        | Purpose             |
| ---------------- | ------------------- |
| `signature (.s)` | describe task       |
| `chain`          | sequential pipeline |
| `group`          | parallel map        |
| `chord`          | map + reduce        |
| `link`           | callback            |
| `link_error`     | error callback      |

These form a **distributed DAG engine**.

---

# 14. Scaling Model (Important)

Celery scales by:

1. more **worker slots** (concurrency)
2. more **worker processes**
3. more **machines / containers**

Broker just hands out tasks to whoever is free.

One task = one slot only.

So you must **split work into many tasks**.

---

# 15. Production Patterns

### Don’t send big data in task args

Send:

* file paths
* DB ids
* S3 keys

Let worker load data itself.

---

### Separate compute from orchestration

Client / API:

* creates workflows

Workers:

* only compute

---

### Use Flower for monitoring

```bash
pip install flower
celery -A app flower --port=5555
```

Shows:

* workers
* queues
* task history

---

# 16. When NOT to use Celery

Celery is bad for:

* fine-grained parallel loops
* GPU tensor parallelism
* tightly coupled workflows

Use:

* multiprocessing
* Ray
* Dask
* PyTorch distributed

Celery is best for:

* job orchestration
* async pipelines
* ML experiment scheduling
* ETL