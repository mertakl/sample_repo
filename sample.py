# django_threadpool.py

from concurrent.futures import ThreadPoolExecutor
from django import db
from functools import wraps


class DjangoThreadPoolExecutor(ThreadPoolExecutor):
    """
    ThreadPoolExecutor that safely manages Django ORM connections.
    """

    def submit(self, fn, *args, **kwargs):
        wrapped_fn = self._wrap_with_db_management(fn)
        return super().submit(wrapped_fn, *args, **kwargs)

    @staticmethod
    def _wrap_with_db_management(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            # Ensure stale/closed connections are cleaned up
            db.close_old_connections()

            try:
                return fn(*args, **kwargs)
            finally:
                # VERY IMPORTANT: close connection used by this thread
                db.connections.close_all()

        return wrapper
