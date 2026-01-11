import json
from raw.config.loader import config

class EnquiryUnit:
    def __init__(self):
        self.storage_type = config['storage_type']
        self.output_directory = config['output_directory']

    def get_task_status(self, task_id):
        if self.storage_type == "filesystem":
            try:
                output_path = f"{self.output_directory}/{task_id}.json"
                with open(output_path, "r") as f:
                    task_data = json.load(f)
                return {
                    "status": task_data.get("status"),
                    "result": task_data.get("result"),
                    "error": task_data.get("error")
                }
            except FileNotFoundError:
                return {"status": "not_found"}
        else:
            return {"status": "storage_not_supported"}
