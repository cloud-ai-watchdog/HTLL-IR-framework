import os, time, random
from celery import Celery
from dotenv import load_dotenv
from app.colorlogger import get_colorlogger
lg = get_colorlogger("cclient")

load_dotenv()

app = Celery("random_number", broker=os.getenv("CELERY_BROKER_URL"))


@app.task
def random_number(max_value: int):
    lg.info(f"I got a max_value {max_value}. Thinking ...")
    time.sleep(2)
    lg.info(f"I have done thinking with {max_value}!")
    return random.randint(0, max_value)


# uv run celery -A app.cworker:app worker --loglevel=info