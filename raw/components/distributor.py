from raw.utils.logger import get_logger
import time
import queue

logger = get_logger(__name__)

class DistributionUnit:
    def __init__(self, pending_tasks_q, backpressure_delay):
        self.pending_tasks_q = pending_tasks_q
        self.backpressure_delay = backpressure_delay
        logger.info("DistributionUnit initialized")

    def distribute_task(self, task, priority):
        try:
            # Use non-blocking put with a timeout for backpressure
            self.pending_tasks_q.put((priority, task), timeout=self.backpressure_delay)
            logger.info(f"Task {task.name} with id {task.id} distributed to pending tasks queue")
        except queue.Full:
            logger.warning("Pending tasks queue is full, task not added.")

    def get_task(self):
        try:
            # Block for a short time to avoid busy-waiting in the dispatcher
            _priority, task = self.pending_tasks_q.get(timeout=0.1)
            return task
        except queue.Empty:
            return None
