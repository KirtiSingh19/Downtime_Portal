# UploadData/celery.py

from __future__ import absolute_import
import os
import logging
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'UploadData.settings')

# Configure logging
log_dir = os.path.join(os.path.dirname(__file__), '../logs')
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(log_dir, "celery.log")),
        logging.StreamHandler()  # Optional: also print to console
    ]
)

app = Celery('UploadData')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
