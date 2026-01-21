from app.worker import map_sq_sum, reduce_sum
from app.colorlogger import get_colorlogger
lg = get_colorlogger("cclient")

def chunk_generator(arr, chunk_size):
	for i in range(0,len(arr),chunk_size):
		yield arr[i:i+chunk_size]


# huge data (example)
data = list(range(1, 1000))   
chunk_size = 100               


def assign(chunk):
	try:
		lg.debug(f"Client assigning a task of len: {len(chunk)}")
		return map_sq_sum.delay(chunk)
	except Exception as e:
		lg.error(f"Exception !!! {e}")
		return None

async_results = [
	assign(chunk) for chunk in chunk_generator(data,chunk_size)
]


print(f"Client submitted {len(async_results)} tasks")


partials = [r.get(timeout=120) for r in async_results]

total = sum(partials) # Not necessary to distribute this 

print("Total sum of squares =", total)