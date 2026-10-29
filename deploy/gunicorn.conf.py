"""
Gunicorn configuration for PyForgeLabs CBT College LAN Deployment.
Engineered for 50+ simultaneous examination workstations over high-speed local ethernet.
"""

import multiprocessing
import os

# Server socket
bind = os.environ.get("GUNICORN_BIND", "127.0.0.1:8000")
backlog = 2048

# Worker processes: 2 x Cores + 1, bounded to 8-12 for predictable RAM utilization
cpu_count = multiprocessing.cpu_count()
workers = int(os.environ.get("GUNICORN_WORKERS", max(4, min(cpu_count * 2 + 1, 12))))
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", 4))
worker_connections = 1000

# Lifecycle & Memory leak prevention (recycles workers after serving N requests)
max_requests = 2000
max_requests_jitter = 150
timeout = 30
keepalive = 5

# Logging
loglevel = "info"
accesslog = "logs/gunicorn_access.log"
errorlog = "logs/gunicorn_error.log"
capture_output = True

# Process naming
proc_name = "pyforgelabs_cbt_web"
