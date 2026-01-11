import yaml
from pathlib import Path
from mocker import generate_mocked_tasks
from queue import PriorityQueue
from concurrent.futures import ThreadPoolExecutor
from models import PrioritizedWriteEntity
from logger import get_colorlogger
from writer import WriterThreadLoop
import time
import datetime
from tqdm import tqdm



def load_config():
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    return config

CONFIG = load_config()
STOP = object()
COLOR_LOGGER = get_colorlogger(name="HTLL-IR@v0")

# Loading specific configuration parameters from CONFIG
WORKERS_COUNT = CONFIG['workers']['count']
WORKERS_TYPE = CONFIG['workers']['type']
PENDING_Q_SZ = CONFIG['queues']['pending_q_sz']
WRITE_Q_SZ = CONFIG['queues']['write_q_sz']
ASYNC_Q_SZ = CONFIG['queues']['async_q_sz']
PERSISTENCE_TYPE = CONFIG['persistence']['type']
PERSISTENCE_OUTPUT_DIR_PATH = CONFIG['persistence']['output_dir_path']
PERSISTENCE_LOG_FILE_PATH = CONFIG['persistence']['log_file_path']
PERSISTENCE_RESULT_FILE_PATH = CONFIG['persistence']['result_file_path']

# Derive additional parameters if needed


# Generate mocked tasks for demonstration
MOCKED_TASKS = generate_mocked_tasks()

# -----------------------------
# Writer Loop
# -----------------------------
WRITER_THREAD_LOOP = WriterThreadLoop(
    log_file_path=PERSISTENCE_LOG_FILE_PATH,
    result_file_path=PERSISTENCE_RESULT_FILE_PATH,
    write_q_sz=WRITE_Q_SZ,
    logger=COLOR_LOGGER
)

# -----------------------------
# AsyncLane per worker
# -----------------------------
import asyncio


class AsyncLane:
    def __init__(self, q_sz):
        self.q_sz = q_sz
        self.


# -----------------------------
# Test Worker Loop
# -----------------------------
def test_worker_thread_loop(
        writer_loop
    ):
    COLOR_LOGGER.info("Test worker started.")
    while True:
        try:
            # Simulate some processing time
            time.sleep(1)
            x = input("Enter how many times to writeq (type 'exit' to quit): ")
            if x.lower() == 'exit':
                COLOR_LOGGER.info("Test worker exiting.")
                break
            COLOR_LOGGER.info(f"Test worker received input: {x}")
            
            if x.isdigit():
                COLOR_LOGGER.info(f"Test worker is generating {x} writer tasks")
                for i in tqdm(range(int(x))):
                    typ = "log" if i%2 else "result"
                    writer_loop.write(
                        priority=i,
                        entity=i,
                        typ=typ
                    )
                COLOR_LOGGER.info(f"Test worker has generated {x} tasks !")
        except Exception as e:
            COLOR_LOGGER.error("Worker loop crashed with exception {e}")





def spawn_manager():
    if WORKERS_TYPE == "thread":
        pending_q = PriorityQueue(maxsize=PENDING_Q_SZ)
        max_threads = WORKERS_COUNT*2 + 1
        with ThreadPoolExecutor(max_workers=max_threads) as executor:
            # writer
            # executor.submit(WRITER_LOOP._start_loop)
            WRITER_THREAD_LOOP.start_in_executer(executor=executor)
            # test worker
            executor.submit(test_worker_thread_loop, WRITER_THREAD_LOOP)


if __name__ == "__main__":
    spawn_manager()