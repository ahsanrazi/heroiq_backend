# Gunicorn configuration for production
# Run: gunicorn app.main:app -c gunicorn.conf.py

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = 4
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 120
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = "info"
