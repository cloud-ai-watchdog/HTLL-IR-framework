from app.cworker import random_number
from app.colorlogger import get_colorlogger
lg = get_colorlogger("cclient")

r = random_number.delay(100)
lg.info(f"Submitted task id: {r.id}")

# IMPORTANT: no backend => you cannot do r.state / r.get()
lg.info("Done (not waiting for result).")