Below are **3 minimal Worker + Client** examples for your exact setup style (`celery/0`, `app/`, `uv`, macOS).
All three use the **same task**, only backend config and client behavior changes.

Assume files:

* `celery/0/.env`
* `celery/0/app/cworker.py`
* `celery/0/app/cclient.py`

And you run everything from `celery/0`.

---

# Case 1 — Broker only (NO result backend) ✅ (no backend URL required)

### `.env`

```env
CELERY_BROKER_URL=amqp://admin:admin@localhost:5672//
```

### `app/cworker.py`

```python
import os, time, random
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

app = Celery("random_number", broker=os.getenv("CELERY_BROKER_URL"))

@app.task
def random_number(max_value: int):
    time.sleep(2)
    return random.randint(0, max_value)
```

### `app/cclient.py`  (fire-and-forget)

```python
from app.cworker import random_number

r = random_number.delay(100)
print("Submitted task id:", r.id)

# IMPORTANT: no backend => you cannot do r.state / r.get()
print("Done (not waiting for result).")
```

**Run**

```bash
uv run celery -A app.cworker:app worker --loglevel=info
uv run python -m app.cclient
```

---

# Case 2 — Redis backend ✅ (persistent results)

### `.env`

```env
CELERY_BROKER_URL=amqp://admin:admin@localhost:5672//
CELERY_RESULT_BACKEND=redis://localhost:6379/1
```

Start Redis (docker):

```bash
docker run -d --name redis -p 6379:6379 redis:7
```

### `app/cworker.py`

```python
import os, time, random
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

app = Celery(
    "random_number",
    broker=os.getenv("CELERY_BROKER_URL"),
    backend=os.getenv("CELERY_RESULT_BACKEND"),
)

@app.task
def random_number(max_value: int):
    time.sleep(2)
    return random.randint(0, max_value)
```

### `app/cclient.py` (wait for result)

```python
from app.cworker import random_number

r = random_number.delay(100)
print("Submitted task id:", r.id)
print("State:", r.state)

print("Result:", r.get(timeout=20))
```

**Run**

```bash
uv run celery -A app.cworker:app worker --loglevel=info
uv run python -m app.cclient
```

---

# Case 3 — RPC backend ✅ (no Redis; results via RabbitMQ, not persistent)

### `.env`

```env
CELERY_BROKER_URL=amqp://admin:admin@localhost:5672//
CELERY_RESULT_BACKEND=rpc://
```

### `app/cworker.py`

```python
import os, time, random
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

app = Celery(
    "random_number",
    broker=os.getenv("CELERY_BROKER_URL"),
    backend=os.getenv("CELERY_RESULT_BACKEND"),  # rpc://
)

@app.task
def random_number(max_value: int):
    time.sleep(2)
    return random.randint(0, max_value)
```

### `app/cclient.py`

```python
from app.cworker import random_number

r = random_number.delay(100)
print("Submitted task id:", r.id)
print("State:", r.state)

print("Result:", r.get(timeout=20))
```

**Run**

```bash
uv run celery -A app.cworker:app worker --loglevel=info
uv run python -m app.cclient
```

**Notes about RPC backend**

* No Redis needed ✅
* Results work with `.get()` ✅
* Not meant for long-lived storage ❌ (best for quick request/response)

---

## Two “gotchas” to avoid (based on your earlier error)

1. Always import with package path in client:

```python
from app.cworker import random_number
```

(not `from cworker import ...`)

2. Run client as module from project root:

```bash
uv run python -m app.cclient
```

---

If you want, I can also give you a **single codebase** that switches between these 3 modes via `.env` only (no code edits), with safe defaults.
