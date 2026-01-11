from raw.models.task import Task, Function, Promise
import uuid
import time
from raw.utils.logger import get_logger

logger = get_logger(__name__)

print("Orchestrator imported")

class Orchestrator:
    def __init__(self, dist_unit):
        self.dist_unit = dist_unit
        logger.info("Orchestrator initialized")

    def create_task_from_function(self, name, func, params, priority=0):
        task_id = str(uuid.uuid4())
        function = Function(id=str(uuid.uuid4()), name=func.__name__, call=func, parameters=params)
        task = Task(
            id=task_id,
            name=name,
            task_type="function",
            executable=function,
        )
        logger.info(f"Created task {task.name} with id {task._id} from function")
        self.dist_unit.distribute_task(task, priority)
        return task_id

    def create_task_from_promise(self, name, promise_future, priority=0):
        task_id = str(uuid.uuid4())
        promise = Promise(id=str(uuid.uuid4()), name=name, future=promise_future)
        task = Task(
            id=task_id,
            name=name,
            task_type="promise",
            executable=promise,
        )
        logger.info(f"Created task {task.name} with id {task.id} from promise")
        self.dist_unit.distribute_task(task, priority)
        return task_id
