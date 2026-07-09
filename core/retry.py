import asyncio
import random
import logging

logger = logging.getLogger(__name__)

async def retry_async(fn, *args, attempts=3, base_delay=0.5, retry_on=(Exception,), **kwargs):
    """
    Retries an async function upon encountering specified exceptions.
    """
    last_exc = None
    for i in range(attempts):
        try:
            return await fn(*args, **kwargs)
        except retry_on as e:
            last_exc = e
            if i < attempts - 1:
                delay = base_delay * (2 ** i) + random.uniform(0, 0.2)
                logger.debug(f"Attempt {i+1} failed with {e}. Retrying in {delay:.2f}s...")
                await asyncio.sleep(delay)
    raise last_exc
