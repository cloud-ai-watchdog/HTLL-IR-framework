Below is a complete **Flask + Celery + WebSocket (Socket.IO)** setup that matches what you asked:

* `POST /do` → submit task with a number `n`
* WebSocket endpoint (Socket.IO) → streams **status + progress % + final result**
* `GET /` or `/index` → serves a basic HTML page via **`render_template`** (not inline)
* Celery task: “heavy” work = sum from `1..n` with a delay, reporting progress

This uses **Redis** for broker+backend (simplest for progress + websockets).

---

## 1) Project structure

```
celery_flask_ws/
├─ .env
├─ pyproject.toml
├─ app/
│  ├─ __init__.py
│  ├─ celery_app.py
│  ├─ tasks.py
│  └─ flask_app.py
├─ templates/
│  └─ index.html
└─ static/
   └─ app.js
```

---

## 2) `.env`

```env
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

FLASK_SECRET_KEY=dev-secret
```

---

## 3) `pyproject.toml` (uv-managed deps)

```toml
[project]
name = "celery-flask-ws"
version = "0.1.0"
requires-python = ">=3.9"
dependencies = [
  "flask>=3.0.0",
  "celery>=5.3.0",
  "redis>=5.0.0",
  "python-dotenv>=1.0.0",
  "flask-socketio>=5.3.0",
  "eventlet>=0.35.0",
]
```

Install:

```bash
uv pip install -r <(python -c "print('')")  # ignore; just do next line
uv pip install flask celery redis python-dotenv flask-socketio eventlet
```

(If you prefer, you can rely on `pyproject.toml` and do `uv sync` if you’re using uv’s project mode.)

---

## 4) `app/celery_app.py`

```python
import os
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

celery_app = Celery(
    "app",
    broker=os.getenv("CELERY_BROKER_URL"),
    backend=os.getenv("CELERY_RESULT_BACKEND"),
)

# Optional, but nice defaults
celery_app.conf.update(
    task_track_started=True,
    result_expires=3600,
)
```

---

## 5) `app/tasks.py` (heavy task + progress updates)

```python
import time
from app.celery_app import celery_app

@celery_app.task(bind=True)
def slow_sum_squares(self, n: int, delay_s: float = 0.01):
    """
    Computes sum_{i=1..n} i^2 slowly, updating progress.
    """
    n = int(n)
    if n < 0:
        raise ValueError("n must be >= 0")

    total = n if n > 0 else 1
    acc = 0

    # Mark STARTED early (Celery can do this automatically too)
    self.update_state(state="PROGRESS", meta={"current": 0, "total": total, "percent": 0})

    for i in range(1, n + 1):
        acc += i * i
        time.sleep(delay_s)

        # Update progress occasionally (every ~1% or every 200 steps)
        if i == n or i % max(1, n // 100) == 0 or i % 200 == 0:
            percent = int((i / total) * 100)
            self.update_state(
                state="PROGRESS",
                meta={"current": i, "total": total, "percent": percent},
            )

    return {"n": n, "sum_squares": acc}
```

---

## 6) `app/flask_app.py` (Flask routes + Socket.IO status streaming)

```python
import os
from flask import Flask, jsonify, request, render_template
from flask_socketio import SocketIO, join_room, emit
from celery.result import AsyncResult
from dotenv import load_dotenv

from app.celery_app import celery_app
from app.tasks import slow_sum_squares

load_dotenv()

def create_app():
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-secret")

    # eventlet is simplest for Socket.IO
    socketio = SocketIO(app, cors_allowed_origins="*")

    @app.get("/")
    @app.get("/index")
    def index():
        return render_template("index.html")

    @app.post("/do")
    def do():
        data = request.get_json(silent=True) or {}
        n = data.get("n")
        if n is None:
            return jsonify({"error": "Missing 'n'"}), 400

        # Enqueue task
        task = slow_sum_squares.delay(int(n))
        return jsonify({"task_id": task.id})

    @app.get("/status/<task_id>")
    def status(task_id: str):
        # Handy REST endpoint too (optional)
        r = AsyncResult(task_id, app=celery_app)
        payload = {"task_id": task_id, "state": r.state}

        if r.state == "PROGRESS":
            payload["progress"] = r.info or {}
        elif r.state == "SUCCESS":
            payload["result"] = r.result
        elif r.state == "FAILURE":
            payload["error"] = str(r.result)

        return jsonify(payload)

    # -----------------------
    # Socket.IO events
    # -----------------------
    @socketio.on("watch_task")
    def watch_task(data):
        """
        Client sends: { task_id: "..." }
        Server joins the client to a room = task_id and starts emitting updates.
        """
        task_id = (data or {}).get("task_id")
        if not task_id:
            emit("task_update", {"error": "task_id required"})
            return

        join_room(task_id)
        emit("task_update", {"task_id": task_id, "state": "WATCHING"}, room=task_id)

        # Background polling loop for this room
        def poll():
            while True:
                r = AsyncResult(task_id, app=celery_app)
                msg = {"task_id": task_id, "state": r.state}

                if r.state == "PROGRESS":
                    info = r.info or {}
                    msg["progress"] = {
                        "current": int(info.get("current", 0)),
                        "total": int(info.get("total", 1)),
                        "percent": int(info.get("percent", 0)),
                    }
                    socketio.emit("task_update", msg, room=task_id)

                elif r.state == "SUCCESS":
                    msg["result"] = r.result
                    socketio.emit("task_update", msg, room=task_id)
                    break

                elif r.state == "FAILURE":
                    msg["error"] = str(r.result)
                    socketio.emit("task_update", msg, room=task_id)
                    break

                else:
                    # PENDING / STARTED etc.
                    socketio.emit("task_update", msg, room=task_id)

                socketio.sleep(0.5)

        socketio.start_background_task(poll)

    return app, socketio

app, socketio = create_app()

if __name__ == "__main__":
    # Note: use socketio.run, not app.run
    socketio.run(app, host="127.0.0.1", port=5000, debug=True)
```

---

## 7) `templates/index.html` (rendered template)

```html
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Flask + Celery + WebSocket Progress</title>
    <style>
      body { font-family: sans-serif; max-width: 700px; margin: 40px auto; }
      .row { margin: 12px 0; }
      input { padding: 8px; width: 180px; }
      button { padding: 8px 12px; cursor: pointer; }
      .box { padding: 10px; border: 1px solid #ddd; border-radius: 8px; }
      .muted { color: #666; }
    </style>
  </head>
  <body>
    <h2>Celery Task Progress (WebSocket)</h2>

    <div class="row">
      <label>Enter n:</label>
      <input id="nInput" type="number" value="5000" min="0" />
      <button id="startBtn">Start</button>
    </div>

    <div class="row box">
      <div><b>Task ID:</b> <span id="taskId" class="muted">-</span></div>
      <div><b>Status:</b> <span id="status" class="muted">-</span></div>
      <div class="row">
        <b>Progress:</b>
        <progress id="progressBar" value="0" max="100"></progress>
        <span id="progressText" class="muted">0%</span>
      </div>
      <div class="row">
        <b>Result:</b>
        <pre id="resultBox" class="muted">-</pre>
      </div>
    </div>

    <!-- Socket.IO client -->
    <script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
    <script src="{{ url_for('static', filename='app.js') }}"></script>
  </body>
</html>
```

---

## 8) `static/app.js` (client logic)

```javascript
const socket = io(); // connects to same host/port
const nInput = document.getElementById("nInput");
const startBtn = document.getElementById("startBtn");

const taskIdEl = document.getElementById("taskId");
const statusEl = document.getElementById("status");
const progressBar = document.getElementById("progressBar");
const progressText = document.getElementById("progressText");
const resultBox = document.getElementById("resultBox");

function resetUI() {
  taskIdEl.textContent = "-";
  statusEl.textContent = "-";
  progressBar.value = 0;
  progressText.textContent = "0%";
  resultBox.textContent = "-";
}

startBtn.addEventListener("click", async () => {
  resetUI();
  const n = Number(nInput.value);

  const resp = await fetch("/do", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ n }),
  });

  const data = await resp.json();
  if (!resp.ok) {
    statusEl.textContent = "ERROR";
    resultBox.textContent = JSON.stringify(data, null, 2);
    return;
  }

  const taskId = data.task_id;
  taskIdEl.textContent = taskId;
  statusEl.textContent = "SUBMITTED";

  socket.emit("watch_task", { task_id: taskId });
});

socket.on("task_update", (msg) => {
  if (msg.error) {
    statusEl.textContent = "ERROR";
    resultBox.textContent = msg.error;
    return;
  }

  if (msg.task_id) taskIdEl.textContent = msg.task_id;
  if (msg.state) statusEl.textContent = msg.state;

  if (msg.progress) {
    const p = Number(msg.progress.percent ?? 0);
    progressBar.value = p;
    progressText.textContent = `${p}%`;
  }

  if (msg.result) {
    progressBar.value = 100;
    progressText.textContent = "100%";
    resultBox.textContent = JSON.stringify(msg.result, null, 2);
  }
});
```

---

## 9) Run it

### Start Redis

```bash
docker run -d --name redis -p 6379:6379 redis:7
```

### Terminal 1: start Celery worker

From project root `celery_flask_ws/`:

```bash
uv run celery -A app.celery_app:celery_app worker --loglevel=info --concurrency 4
```

### Terminal 2: start Flask + Socket.IO server

```bash
uv run python app/flask_app.py
```

Open:

* [http://127.0.0.1:5000/](http://127.0.0.1:5000/)

---

## Notes that matter

* WebSocket progress needs a **result backend** (Redis) because progress meta/state is stored there.
* The “status streaming” here is implemented by **server polling AsyncResult** and pushing updates via WebSocket. It’s simple and works well for a single-node dev setup.

If you want, I can also show the next step: **no polling** (push-style) using Celery events or pub/sub so updates are emitted immediately without periodic checks.
