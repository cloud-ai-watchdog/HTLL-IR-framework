from models import Task, Function, Promise, SchedulerContext
import asyncio
import random
import threading
import os
import time
import datetime


# -----------------------------
# Demo workloads
# -----------------------------
def cpuish(x: int) -> int:
    print("cpuish sync task started, doing CPU work")
    s = 0
    for i in range(200_000):
        s += (i % 7)
    res = x * x + (s % 97)
    print("cpuish sync task completed")
    return res

async def ioish_async(x: int) -> str:
    print("ioish async task started")
    await asyncio.sleep(random.uniform(0.2, 1.0))
    print("ioish async task completed")
    return f"async-ok-{x}"


def generate_mocked_tasks():
    mocked_tests = []

    for i in range(10):
        if i % 2 == 0:
            func = Function(
                id_=str(i),
                name=f"cpuish-{i}",
                call=cpuish,
                parameters={"x": i}
            )
            scheduler_context = SchedulerContext(
                thread_id=threading.current_thread().name,
                process_id=str(os.getpid()),
                schedule_timestamp=str(datetime.datetime.now())
            )
            task = Task(
                id_=f"_task_{i}",
                name=f"cpuish-task-{i}",
                task_type="function",
                executable=func,
                scheduler_context=scheduler_context
            )
        else:
            promise_future = ioish_async(i)
            promise = Promise(
                id_=str(i),
                name=f"ioish-{i}",
                future=promise_future
            )
            scheduler_context = SchedulerContext(
                thread_id=threading.current_thread().name,
                process_id=str(os.getpid()),
                schedule_timestamp=str(datetime.datetime.now())
            )
            task = Task(
                id_=f"_task_{i}",
                name=f"ioish-task-{i}",
                task_type="promise",
                executable=promise,
                scheduler_context=scheduler_context
            )
        mocked_tests.append(task)
    return mocked_tests


if __name__ == "__main__":
    mocked_tests = generate_mocked_tasks()
    for t in  mocked_tests:
        if t.task_type == "function":
            result = t.executable.call(**t.executable.parameters)
            print(f"Task {t.id_} result: {result}")
        elif t.task_type == "promise":
            loop = asyncio.get_event_loop()
            result = loop.run_until_complete(t.executable.future)
            print(f"Task {t.id_} result: {result}")