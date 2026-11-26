"""
gunicorn faqat Flask health-check uchun ishlatilsa.
Polling uchun python app.py ishlatish tavsiya etiladi.
"""
import os

bind            = f"0.0.0.0:{os.getenv('PORT', '10000')}"
workers         = 1
worker_class    = "gthread"
threads         = 4
timeout         = 120
graceful_timeout = 30
keepalive       = 5
preload_app     = False
accesslog       = "-"
errorlog        = "-"
loglevel        = "info"
