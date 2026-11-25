import encodings.idna  # noqa: F401
import os

bind = f"0.0.0.0:{os.getenv('PORT', '10000')}"
# MUHIM: bitta worker. Bot, Dispatcher va asyncio loop jarayon ichida bir marta ishga tushadi.
# Parallellik thread'lar orqali ta'minlanadi.
workers = 1
worker_class = "gthread"
threads = 8
timeout = 120
graceful_timeout = 30
keepalive = 5
preload_app = False
accesslog = "-"
errorlog = "-"
loglevel = "info"


# ---- diagnostika: worker hayoti logga yoziladi ----
def post_worker_init(worker):
    worker.log.info("Worker tayyor: pid=%s", worker.pid)


def worker_int(worker):
    worker.log.warning("Worker SIGINT oldi: pid=%s", worker.pid)


def worker_abort(worker):
    worker.log.error("Worker abort (timeout?): pid=%s", worker.pid)


def worker_exit(server, worker):
    server.log.warning("Worker chiqdi: pid=%s", worker.pid)
