# utils.py

import asyncio
import logging
# Make sure to add this import
from typing import Awaitable, Callable, AsyncIterator

# Assuming these are defined in your project
from fortis.conversation.assistant import Assistant, AssistantResponse, StreamingAssistantResponse
from fortis.conversation.message import Conversation, UserMessage
from yara_samy.errors import GuardrailError


async def _stream_guardrail_error(error: GuardrailError) -> AsyncIterator[dict]:
    """Wraps a GuardrailError in an async generator to mimic a stream."""
    yield {"type": "error", "data": {"content": error.message}}


class GuardedAssistant(Assistant):
    """Assistant with input and output guardrail."""

    underlying_assistant: Assistant
    input_guard: Callable[[str], Awaitable[None]] = None
    output_guard: Callable[[str], Awaitable[None]] = None

    async def next_message(self, conversation: Conversation, **kwargs) -> AssistantResponse:
        """Generates the assistant answer with guardrails. (Non-streaming)"""
        assert len(conversation.messages) > 0
        last_message = conversation.messages[-1]
        assert isinstance(last_message, UserMessage), "The conversation should end with a UserMessage"

        if self.input_guard:
            try:
                _, response = await asyncio.gather(
                    self.input_guard(last_message.string_content),
                    self.underlying_assistant.next_message(conversation=conversation, **kwargs),
                )
            except GuardrailError as error:
                logging.info(f"Guardrail triggered for input message {last_message}")
                return AssistantResponse(content=error.message)
        else:
            response = await self.underlying_assistant.next_message(conversation=conversation, **kwargs)

        if self.output_guard:
            try:
                await self.output_guard(response.content)
            except GuardrailError as error:
                logging.info(f"Guardrail triggered for output message {response}")
                return AssistantResponse(content=error.message)
        return response

    async def next_message_stream(self, conversation: Conversation, **kwargs) -> AsyncIterator[dict]:
        """
        Generates the assistant answer stream with an input guardrail.

        NOTE: The output guardrail is NOT applied in streaming mode to ensure low
        latency. The output guardrail requires the full response to be generated
        before validation, which defeats the purpose of streaming.
        """
        assert len(conversation.messages) > 0
        last_message = conversation.messages[-1]
        assert isinstance(last_message, UserMessage), "The conversation should end with a UserMessage"

        if self.input_guard:
            try:
                await self.input_guard(last_message.string_content)
            except GuardrailError as error:
                logging.info(f"Input guardrail triggered for message: {last_message}")
                return _stream_guardrail_error(error)

        # If the input guard passes, stream from the underlying assistant.
        # The output guard is intentionally bypassed for performance.
        async for chunk in self.underlying_assistant.next_message_stream(conversation=conversation, **kwargs):
            yield chunk
