I’ll give you:

1. ✅ `link` and `link_error` (success & failure callbacks)
2. ✅ `chain` pipeline example (data → preprocess → train → evaluate)
   with **full worker + client code** style.

Assume:

* Redis backend enabled
* RabbitMQ/Redis broker working

---

# ✅ 1. `link` and `link_error` — success & failure callbacks

## 🎯 Use case

After task finishes:

* on success → log / store result
* on failure → alert / cleanup / retry pipeline

---

## Worker: `app/worker.py`

```python
import os, time, random
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

app = Celery(
    "demo",
    broker=os.getenv("CELERY_BROKER_URL"),
    backend=os.getenv("CELERY_BACKEND_URL"),
)

# -----------------------
# Main task
# -----------------------
@app.task
def risky_division(x, y):
    time.sleep(2)
    return x / y   # may crash if y == 0

# -----------------------
# Success callback
# -----------------------
@app.task
def on_success(result):
    print("✅ SUCCESS CALLBACK: result =", result)

# -----------------------
# Failure callback
# -----------------------
@app.task
def on_fail(request, exc, traceback):
    print("❌ FAILURE CALLBACK:", exc)
```

⚠️ Failure callback receives `(request, exc, traceback)` — different signature!

---

## Client: `app/client.py`

```python
from app.worker import risky_division, on_success, on_fail

sig = risky_division.s(10, 0)  # will fail

sig.link(on_success.s())
sig.link_error(on_fail.s())

sig.apply_async()
print("Task submitted")
```

---

## What happens

If success:

```
risky_division → on_success(result)
```

If failure:

```
risky_division → on_fail(request, exception, traceback)
```

Callbacks run as **separate Celery tasks**, not in client.

---

# ✅ 2. `chain` — ML-style pipeline

## 🎯 Use case

Classic ML pipeline:

```
load → preprocess → train → evaluate
```

Each step runs on worker, possibly different machines.

---

## Worker: `app/worker.py`

```python
@app.task
def load_data():
    print("Loading data...")
    return [1, 2, 3, 4, 5]

@app.task
def preprocess(data):
    print("Preprocessing...")
    return [x * 2 for x in data]

@app.task
def train_model(data):
    print("Training model...")
    model = {"mean": sum(data) / len(data)}
    return model

@app.task
def evaluate(model):
    print("Evaluating...")
    return {"accuracy": model["mean"] / 10}
```

---

## Client: `app/client.py`

```python
from celery import chain
from app.worker import load_data, preprocess, train_model, evaluate

job = chain(
    load_data.s(),
    preprocess.s(),
    train_model.s(),
    evaluate.s(),
)()

print("Final result:", job.get(timeout=60))
```

---

## What happens internally

1. Worker runs `load_data()`
2. Its result is sent to `preprocess(data)`
3. Then into `train_model(data)`
4. Then into `evaluate(model)`
5. Final output returned to client

Each step may run on **different workers**.

---

# 🔥 Advanced: combine chain + group + chord

Example: preprocess in parallel, then train.

```
load
 ↓
group(preprocess chunks)
 ↓
reduce
 ↓
train
```

That’s how you build **distributed ML pipelines** in Celery.

---

# ⚠️ Important design notes

### ✔ Callbacks are async tasks

They do NOT block original task.

### ✔ Chains propagate failure

If `train_model` fails:

* `evaluate` will NOT run

### ✔ link_error is per-task

Chains have their own error handling too.

---

# When to use what

| Pattern      | Use                      |
| ------------ | ------------------------ |
| `link`       | fire callback after task |
| `link_error` | notify on failure        |
| `chain`      | linear pipeline          |
| `group`      | parallel batch           |
| `chord`      | map-reduce               |

These form Celery’s **distributed DAG engine**.

