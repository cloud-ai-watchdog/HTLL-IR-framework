from queue import PriorityQueue
# -----------------------------
# Completion accounting (no threading import)
# Uses a blocking Queue as a notification channel
# -----------------------------
class CompletionCounter:
    def __init__(self, total: int):
        self.total = total
        self._tokens = PriorityQueue()

    def done(self):
        self._tokens.put((0, time.time(), 1))

    def wait_all(self):
        for _ in range(self.total):
            self._tokens.get()  # blocks


# -----------------------------
# AsyncLane per worker
# -----------------------------
import asyncio
from typing import Any, Callable, Optional, Tuple, List
from concurrent.futures import ThreadPoolExecutor
import time
from models import Task, PrioritizedTask

STOP = object()

class AsyncLane:
    """
    One asyncio event loop running in one dedicated thread.
    It has a *private* asyncio.Queue and processes only this worker's promise tasks.
    No semaphore needed: use bounded asyncio.Queue for backpressure if desired.
    """
    def __init__(self, worker_id: int, qmax: int = 1000):
        self.worker_id = worker_id
        self.qmax = qmax
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._started = False

    def start_in_executor(self, executor: ThreadPoolExecutor):
        """
        Start the loop runner in one executor thread.
        Wait until loop + async queue are ready.
        """
        if self._started:
            return

        executor.submit(self._loop_runner)
        # minimal wait until loop is ready (no threading primitives; tiny sleep)
        while self._loop is None:
            time.sleep(0.002)

        self._started = True

    def _loop_runner(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        self._loop = loop
        self._async_q = asyncio.Queue(maxsize=self.qmax)

        loop.create_task(self._async_subworker())
        loop.run_forever()

    async def _async_subworker(self):
        """
        Consumes (task, done_cb) from this worker's private asyncio.Queue.
        """
        while True:
            print(f"Waiting ... len(_async_q) = {(self._async_q.qsize())}")
            item = await self._async_q.get()
            if item is STOP:
                print("Stopping ...")
                # graceful stop
                asyncio.get_event_loop().stop()
                return

            task, done_cb = item
            try:
                print("Executing ")
                result = await task.executable.future
                print(f"==> ",result)
                done_cb(task, "success", result, None)
            except Exception as e:
                print("Errrrror !! ",e)
                done_cb(task, "error", None, repr(e))

    def submit(self, task: Task, done_cb: Callable):
        if not self._started or self._loop is None:
            raise RuntimeError(f"AsyncLane(worker={self.worker_id}) not started")

        async def _put():
            print("_put : ", task.id_)
            await self._async_q.put((task, done_cb))  # bounded -> natural backpressure

        print("submit : ", task.id_)
        asyncio.run_coroutine_threadsafe(_put(), self._loop)

    def stop(self):
        if self._loop is None:
            return

        async def _stop():
            await self._async_q.put(STOP)

        asyncio.run_coroutine_threadsafe(_stop(), self._loop)



from mocker import generate_mocked_tasks
# Generate mocked tasks for demonstration
MOCKED_TASKS = generate_mocked_tasks()


# -----------------------------
# Completion accounting (no threading import)
# Uses a blocking Queue as a notification channel
# -----------------------------
class CompletionCounter:
    def __init__(self, total: int):
        self.total = total
        self._tokens = PriorityQueue()

    def done(self):
        self._tokens.put((0, time.time(), 1))

    def wait_all(self):
        for _ in range(self.total):
            self._tokens.get()  # blocks

completions = CompletionCounter(total=10)

def on_async_done(task: Task, status: str, result: Any, err: Optional[str]):
    completions.done()

if __name__ == "__main__":
    async_lane = AsyncLane(
        worker_id=1,
        qmax=1000
    )
    with ThreadPoolExecutor(max_workers=1) as executor: 
        async_lane.start_in_executor(executor=executor)
        for t in MOCKED_TASKS:
            if t.task_type=="promise":
                print("Submitting task ",t.id_)
                async_lane.submit(
                    t,
                    on_async_done
                )