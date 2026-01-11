import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from raw.components.orchestrator import Orchestrator
from raw.components.distributor import DistributionUnit
from raw.components.worker import execute_task
from raw.components.writer import WriterUnit
from raw.components.enquiry import EnquiryUnit
from raw.config.loader import config
from raw.utils.logger import get_logger

import threading
import time
import asyncio
import queue
import multiprocessing
from queue import PriorityQueue as ThreadPriorityQueue
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from multiprocessing.managers import BaseManager


logger = get_logger(__name__)

# Manager setup for process-safe PriorityQueue
class PriorityQueueManager(BaseManager):
    pass

PriorityQueueManager.register('PriorityQueue', ThreadPriorityQueue)

def get_manager():
    manager = PriorityQueueManager()
    manager.start()
    return manager

def sample_function(x, y):
    logger.info(f"Executing sample_function with args: {x}, {y}")
    return x + y

async def sample_promise():
    logger.info("Executing sample_promise")
    await asyncio.sleep(2)
    return "Promise resolved"

class Framework:
    def __init__(self):
        self.is_running = False
        self.manager = None

        if not os.path.exists(config['output_directory']):
            os.makedirs(config['output_directory'])
        
        self.framework_mode = config.get('framework_mode', 'thread')
        
        if self.framework_mode == 'process':
            self.manager = get_manager()
            pending_tasks_q = self.manager.PriorityQueue(config['pending_tasks_q_size'])
            write_entity_q = self.manager.Queue(config['write_entity_q_size'])
            self.executor = ProcessPoolExecutor(max_workers=config['max_workers'])
        else:
            pending_tasks_q = ThreadPriorityQueue(config['pending_tasks_q_size'])
            write_entity_q = queue.Queue(config['write_entity_q_size'])
            self.executor = ThreadPoolExecutor(max_workers=config['max_workers'])

        self.dist_unit = DistributionUnit(pending_tasks_q, config['backpressure_delay'])
        self.writer_unit = WriterUnit(write_entity_q)
        self.orchestrator = Orchestrator(self.dist_unit)
        self.enquiry_unit = EnquiryUnit()

        logger.info(f"Framework initialized with {self.framework_mode} executor.")

    def _dispatch_tasks(self):
        """Continuously polls for tasks and submits them to the executor."""
        logger.info("Task dispatcher started")
        while self.is_running:
            task = self.dist_unit.get_task()
            if task:
                self.executor.submit(execute_task, self.writer_unit, task, self.framework_mode)
        logger.info("Task dispatcher stopped")

    def start(self):
        self.is_running = True
        
        self.writer_thread = threading.Thread(target=self.writer_unit.start)
        self.writer_thread.daemon = True
        self.writer_thread.start()
        logger.info("Writer unit started")

        self.dispatcher_thread = threading.Thread(target=self._dispatch_tasks)
        self.dispatcher_thread.start()
        
        logger.info("Framework started")

    def stop(self):
        logger.info("Stopping framework...")
        self.is_running = False
        
        self.dispatcher_thread.join()
        logger.info("Task dispatcher stopped.")

        self.executor.shutdown(wait=True)
        logger.info("Executor shut down.")

        self.writer_unit.stop()
        self.writer_thread.join()
        logger.info("Writer unit stopped.")

        if self.framework_mode == 'process' and self.manager:
            self.manager.shutdown()
            logger.info("Manager shut down.")

if __name__ == "__main__":
    framework = Framework()
    framework.start()

    task1_id = framework.orchestrator.create_task_from_function(
        "Sample Task 1", sample_function, [10, 20], priority=1
    )
    task2_id = framework.orchestrator.create_task_from_promise(
        "Sample Task 2", sample_promise(), priority=0
    )

    time.sleep(5)

    status1 = framework.enquiry_unit.get_task_status(task1_id)
    status2 = framework.enquiry_unit.get_task_status(task2_id)

    logger.info(f"Task 1 status: {status1}")
    logger.info(f"Task 2 status: {status2}")

    framework.stop()
