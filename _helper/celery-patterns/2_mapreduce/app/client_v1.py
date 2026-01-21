from app.worker import map_sq_sum, reduce_sum
from app.colorlogger import get_colorlogger

from celery import chord,group

lg = get_colorlogger("cclient")

def chunk_generator(arr, chunk_size):
	for i in range(0,len(arr),chunk_size):
		yield arr[i:i+chunk_size]


# huge data (example)
n = 1000
data = list(range(1, n))   
chunk_size = 100               


def assign(chunk):
	try:
		return map_sq_sum.delay(chunk)
	except Exception as e:
		lg.error(f"Exception !!! {e}")
		return None

# async_results = [
# 	assign(chunk) for chunk in chunk_generator(data,chunk_size)
# ]
# print(f"Client submitted {len(async_results)} tasks")
# partials = [r.get(timeout=120) for r in async_results]
# total = sum(partials) # Not necessary to distribute this 

# print("Total sum of squares =", total)



# Compare the 3 ways to call a Celery task
# 1️⃣ .delay() → execute immediately (send to broker)
# 2️⃣ .apply_async() → execute immediately (more control)
# 3️⃣ .s() → create signature (no execution)


# Celery supports distributed workflows
# group → parallel map, Returns list of results, but no reduce task.
# chain → pipeline
# chord → map + reduce
# link → callbacks
# All of these need task descriptions, not already-executing tasks.



header = [map_sq_sum.s(chunk) for chunk in chunk_generator(data, chunk_size)]

job = chord(header)(reduce_sum.s()) # If you used .delay(), Celery could not build this graph
# More better: job = chord(header)(body).on_error(err_handler.s())
print("Chord submitted. Task id:", job.id)
if job.ready():
	print("Final result:", job.get(timeout=180))
print(f"Correct answer: {sum([d**2 for d in data])}")


# Bonus
g = group(map_sq_sum.s(chunk) for chunk in chunk_generator(data, chunk_size))
gjob = g.apply_async()
if gjob.ready():
	print("Group result:", gjob.get(timeout=180))





