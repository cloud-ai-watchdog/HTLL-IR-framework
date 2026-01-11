from pydantic import BaseModel, Field
from typing import Any, Union, Literal


class Function(BaseModel):
    _id: str = Field(description="Unique identifier for the function")
    name: str = Field(description="Name of the function")
    call: callable = Field(description="The callable function object")
    parameters: list[Any] = Field(description="List of parameters for the function")
    result: Any = Field(default=None, description="Result of the function execution")


class Promise(BaseModel):
    _id: str = Field(description="Unique identifier for the promise")
    name: str = Field(description="Name of the promise")
    future: Any = Field(description="An async future object representing the promise") 
    status: Literal["pending", "running", "success", "error", "waiting"] = Field(default="pending", description="Current status of the promise")
    result: Any = Field(default=None, description="Result of the promise when resolved")


class SchedulerContext(BaseModel):
    thread_id: str = Field(description="Identifier for the thread that scheduled the task")
    process_id: str = Field(description="Identifier for the process that scheduled the task")
    schedule_timestamp: str = Field(description="Timestamp when the task was scheduled")

class ExecutionContext(BaseModel):
    thread_id: str = Field(default=None, description="Identifier for the thread executing the task")
    process_id: str = Field(default=None, description="Identifier for the process executing the task")
    start_time: str = Field(default=None, description="Timestamp when the task execution started")
    end_time: str = Field(default=None, description="Timestamp when the task execution ended")

class Task(BaseModel):
    _id: str = Field(description="Unique identifier for the task")
    name: str = Field(description="Name of the task")
    task_type: Literal["function", "promise"] = Field(description="Type of the task")
    executable = Union[Promise, Function] = Field(description="The executable entity, either a Function or a Promise Object")
    status: Literal["pending", "running", "success", "error", "waiting"] = Field(default="pending", description="Current status of the task")
    scheduler_context: Union[SchedulerContext, None] = Field(default=None, description="Context information from the scheduler")
    execution_context: Union[ExecutionContext, None] = Field(default=None, description="Context information from the execution")
    dependencies: list[str] = Field(default=[], description="List of task IDs that this task depends on")
    save_output: bool = Field(default=True, description="Whether to save the output of this task")
    output_location: str = Field(default=None, description="Location where the output is saved")
    result: Any = Field(default=None, description="Result of the task execution")
    error: str = Field(default=None, description="Error message if the task failed")    