import requests
from apscheduler.events import EVENT_ALL, JobExecutionEvent
from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger
from pytz import utc
from sentry_sdk import capture_exception

from telegram_bot.settings import redis_config

jobstores = {
    "default": RedisJobStore(
        host=redis_config.host, port=redis_config.port, password=redis_config.password
    )
}
job_defaults = {}
executors = {
    "default": {"type": "threadpool", "max_workers": 10},
}


def my_listener(event: JobExecutionEvent):
    if isinstance(event, JobExecutionEvent):
        logger.info(f"my_listener: {event.scheduled_run_time}")
        if event.exception:
            capture_exception(error=event.exception)
            logger.exception(str(event.exception), "The job crashed :(")
    else:
        logger.info(f"my_listener: {event}")


def task_cron():
    logger.info("task_cron started...")
    requests.get("http://localhost:8080/cron")


def task_cron_1h():
    logger.info("task_cron_1h started...")
    requests.get("http://localhost:8080/cron_1h")


scheduler = AsyncIOScheduler(timezone=utc)
scheduler.add_job(task_cron, "cron", hour="*")
scheduler.add_job(task_cron_1h, "cron", hour="*")
scheduler.add_listener(my_listener, EVENT_ALL)
