
"""
Mock LLM service that streams a simple "Hello world" message.
"""

import asyncio
import logging
from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


class LLMService:
    """Mock LLM service that streams a "Hello world" message."""

    def __init__(self) -> None:
        """Initialize mock LLM service."""
        logger.info("Mock LLMService initialized")

    async def generate_streaming(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """
        Generate mock streaming response.

        Args:
            messages: List of messages (ignored in mock)
            temperature: Temperature parameter (ignored in mock)
            max_tokens: Max tokens parameter (ignored in mock)

        Yields:
            str: Text deltas spelling out "Hello world"
        """
        mock_message = "Hello world"
        
        for char in mock_message:
            await asyncio.sleep(0.1)  # Simulate streaming delay
            yield char
