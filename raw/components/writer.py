import queue
from raw.config.loader import config
from raw.utils.logger import get_logger
import json

logger = get_logger(__name__)

class WriterUnit:
    def __init__(self, write_entity_q):
        self.write_entity_q = write_entity_q
        self.storage_type = config['storage_type']
        self.output_directory = config['output_directory']
        self.is_running = False
        logger.info("WriterUnit initialized")

    def start(self):
        self.is_running = True
        logger.info("WriterUnit started")
        while self.is_running or not self.write_entity_q.empty():
            try:
                item = self.write_entity_q.get(timeout=0.1)
                if item:
                    self.persist(item)
            except queue.Empty:
                if not self.is_running:
                    break

    def stop(self):
        self.is_running = False
        logger.info("WriterUnit stopping")

    def write_task_result(self, task):
        self.write_entity_q.put(task)
        logger.info(f"Task {task.name} with id {task.id} sent to writer unit")

    def persist(self, task):
        if self.storage_type == "filesystem":
            self.persist_to_filesystem(task)
        else:
            logger.error("Storage type not supported")

    def persist_to_filesystem(self, task):
        output_path = f"{self.output_directory}/{task.id}.json"
        with open(output_path, "w") as f:
            # Pydantic models have a model_dump() method for serialization in v2
            executable_dict = task.executable.model_dump()
            if 'call' in executable_dict:
                executable_dict['call'] = str(executable_dict['call'])

            task_dict = task.model_dump()
            task_dict['executable'] = executable_dict
            
            json.dump(task_dict, f, indent=4)
        logger.info(f"Task {task.id} persisted to {output_path}")

