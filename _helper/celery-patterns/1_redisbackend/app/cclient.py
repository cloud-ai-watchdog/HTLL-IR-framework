from app.cworker import random_number
from app.colorlogger import get_colorlogger
lg = get_colorlogger("cclient")

try:
	r = random_number.delay(100)
	lg.info(f"Submitted task id: {r.id}")
	lg.info(f"State: {r.state}")

	lg.info(f"Result: {r.get(timeout=20)}")
	lg.info("Done!")
except Exception as e:
	lg.error(f"Exception handled {e}")
	