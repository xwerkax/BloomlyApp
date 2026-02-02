import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'bloomly_app.settings')

app = Celery('bloomly_app')

app.config_from_object('django.conf:settings', namespace='CELERY')

app.autodiscover_tasks()

app.conf.beat_schedule = {}

app.conf.timezone = 'Europe/Warsaw'

@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')