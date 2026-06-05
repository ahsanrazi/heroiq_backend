# Gunicorn configuration for production
# Run: gunicorn app.main:app -c gunicorn.conf.py

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
# Async uvicorn workers, I/O-bound app: ~2 per vCPU. Driven by WEB_CONCURRENCY so
# each instance size sets its own value (os.cpu_count() is unsafe in containers —
# it reports the HOST cores, not the cgroup vCPU limit, and would over-provision).
workers = int(os.environ.get("WEB_CONCURRENCY", 2))
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 120
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = "info"
