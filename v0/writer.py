from ndjson import NdJsonHandler
import time
import datetime
from models import PrioritizedWriteEntity
from queue import PriorityQueue
from concurrent.futures import ThreadPoolExecutor
import threading
import os
from typing import Any

STOP = object()

class WriterThreadLoop:
    def __init__(self,
                 log_file_path,
                 result_file_path,
                 write_q_sz,
                 logger
                 ):
        self._log_file_path = log_file_path
        self._result_file_path = result_file_path
        self._logger = logger
        self._nd_write = NdJsonHandler.write
        self._write_q = PriorityQueue(maxsize=write_q_sz)
    
    def _start_loop(self):
        self._logger.info(f"Writer started at [ python-thread-id {threading.get_ident()} / native-thread-id {threading.get_native_id()} / process-id {os.getpid()} ], waiting for tasks...")
        while True:
            try:
                writable: PrioritizedWriteEntity = self._write_q.get()
                entity = writable.entity
                typ = writable.typ
                if entity is STOP:
                    self._logger.info("Writer received STOP signal. Exiting.")
                    return
                elif typ == "log":
                    time.sleep(1)  # Simulate some processing time
                    NdJsonHandler.write(
                        entity={"timestamp": datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S'),"result":entity},
                        file_path=self._log_file_path
                    )
                elif typ == "result":
                    time.sleep(2)  # Simulate some processing time
                    NdJsonHandler.write(
                        entity={"timestamp": datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S'),"result":entity},
                        file_path=self._result_file_path
                    )
                else:
                    self._logger.error(f"Could not write")
            except Exception:
                self._logger.error(f"Writer crashed while handling write task. Skipping this writable {writable} ...")
            finally:
                pass
                # self._logger.info("One writer queue element processed")


    def write(self, 
              priority:int, 
              entity:Any, 
              typ: str):
        
        try:
            self._write_q.put(
                            PrioritizedWriteEntity(
                                priority=priority,
                                entity=entity,
                                typ=typ
                            )
                        )
        except Exception as e:
            self._logger.error(f"Error while pushing to write q : {e}")
        
    def start_in_executer(self, executor:ThreadPoolExecutor):
        self._logger.info("Writer loop initializing ...")
        executor.submit(self._start_loop)
        self._logger.info("Writer loop initialized !")
    
     