from raw.utils.logger import get_logger
import asyncio
import os
import threading

logger = get_logger(__name__)

def execute_task(writer_unit, task, framework_mode):
    """Executes a single task and sends the result to the writer unit."""
    worker_id = threading.get_ident() if framework_mode == 'thread' else os.getpid()
    logger.info(f"Worker {worker_id} executing task {task.name} with id {task.id}")
    task.status = "running"
    try:
        if task.task_type == "function":
            result = task.executable.call(*task.executable.parameters)
            task.result = result
            task.status = "success"
        elif task.task_type == "promise":
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(task.executable.future)
            task.result = result
            task.status = "success"
        
        writer_unit.write_task_result(task)

    except Exception as e:
        task.error = str(e)
        task.status = "error"
        logger.error(f"Error executing task {task.name} with id {task.id}: {e}")
        writer_unit.write_task_result(task)
