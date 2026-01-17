"""
Streaming Utilities.
Helper classes for handling synchronous streams in asynchronous contexts.
"""
import asyncio
import concurrent.futures
from typing import AsyncGenerator, Callable, Any, Optional

from src.utils.logger import setup_logger

logger = setup_logger(__name__)

class ThreadedStreamer:
    """
    Bridges a synchronous iterator (e.g. standard LLM stream) to an async generator
    by running the synchronous consumption in a separate thread.
    """
    
    @staticmethod
    async def stream_from_sync(
        sync_generator_func: Callable[[], Any],
        timeout: float = 30.0,
        logger_context: str = "Stream"
    ) -> AsyncGenerator[Any, None]:
        """
        Consumes a synchronous generator in a thread and yields items asynchronously.
        
        Args:
            sync_generator_func: A callable that returns the synchronous iterator.
                                 Ensure this function encompasses the *creation* and *iteration* logic if needed,
                                 or just pass a lambda calling the generator.
            timeout: Timeout in seconds for waiting for the next chunk.
            logger_context: Prefix for log messages.
            
        Yields:
             Items produced by the synchronous generator.
        """
        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        
        def run_in_thread():
            try:
                count = 0
                iterator = sync_generator_func()
                
                for item in iterator:
                    count += 1
                    # Thread-safe put
                    loop.call_soon_threadsafe(queue.put_nowait, item)
                    
                logger.debug(f"[{logger_context}] Thread completed: {count} items")
            except Exception as e:
                logger.error(f"[{logger_context}] Thread error: {e}")
                pass
            finally:
                # Sentinel
                loop.call_soon_threadsafe(queue.put_nowait, None)

        # Run thread
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = loop.run_in_executor(executor, run_in_thread)
        
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=timeout)
                    if item is None:
                        break
                    yield item
                except asyncio.TimeoutError:
                    logger.warning(f"[{logger_context}] Timeout waiting for chunk")
                    break
        finally:
            executor.shutdown(wait=False)
