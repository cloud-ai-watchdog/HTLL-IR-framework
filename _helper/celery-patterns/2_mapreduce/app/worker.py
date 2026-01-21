from celery import Celery
from dotenv import load_dotenv
import os 
from app.colorlogger import get_colorlogger
lg = get_colorlogger("worker")


load_dotenv();

print(f"CELERY_BROKER_URL: {os.getenv('CELERY_BROKER_URL')}")
print(f"CELERY_BACKEND_URL: {os.getenv('CELERY_BACKEND_URL')}")


celery_app = Celery(
		"celery_app",
		broker=os.getenv("CELERY_BROKER_URL"),
		backend=os.getenv("CELERY_BACKEND_URL")
	);


@celery_app.task
def map_sq_sum(chunk):
	lg.debug(f"Received a task of len: {len(chunk)}")
	res = sum([c**2 for c in chunk])
	return res

@celery_app.task
def reduce_sum(sums):
	res = sum(sums)
	return res