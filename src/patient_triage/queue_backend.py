"""
Redis/RQ queue accessors for the distributed deployment mode
(TRIAGE_QUEUE_BACKEND=distributed). Only imported when that mode is active,
so Redis/RQ stay optional dependencies (the `scale` extra) for everyone
running the default single-machine setup.
"""
try:
    import redis
    from rq import Queue
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "Distributed queue mode requires the 'scale' extra: pip install patient-triage[scale]"
    ) from e

from . import config


def get_redis_connection():
    return redis.from_url(config.REDIS_URL)


def get_queue() -> "Queue":
    return Queue(config.RQ_QUEUE_NAME, connection=get_redis_connection())
