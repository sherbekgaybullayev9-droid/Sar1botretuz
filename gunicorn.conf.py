"""
Render uchun gunicorn. MUHIM: workers = 1 (holat/keshlar va webhook o'rnatish
bitta jarayonda bo'lishi kerak), parallellik threadlar orqali.
"""
import os

bind = f"0.0.0.0:{os.getenv('PORT', '10000')}"
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
