import asyncio
import logging
from typing import AsyncGenerator, Callable, Awaitable

class GuardedAssistant(Assistant):
    """Assistant with input and output guardrail."""

    underlying_assistant: Assistant
    input_guard: Callable[[str], Awaitable[None]] = None
    output_guard: Callable[[str], Awaitable[None]] = None

    async def next_message(self, conversation: Conversation, **kwargs) -> AssistantResponse:
        """Generates the assistant answer with guardrails."""
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

    async def next_message_stream(self, conversation: Conversation, **kwargs) -> AsyncGenerator[AssistantResponse, None]:
        """Streaming version of next_message with guardrails."""
        assert len(conversation.messages) > 0
        last_message = conversation.messages[-1]
        assert isinstance(last_message, UserMessage), "The conversation should end with a UserMessage"
        
        # Check input guard first
        if self.input_guard:
            try:
                await self.input_guard(last_message.string_content)
            except GuardrailError as error:
                logging.info(f"Guardrail triggered for input message {last_message}")
                yield AssistantResponse(content=error.message)
                return
        
        # Check if underlying assistant supports streaming
        if not hasattr(self.underlying_assistant, 'next_message_stream'):
            # Fallback to non-streaming version
            response = await self.next_message(conversation=conversation, **kwargs)
            yield response
            return
        
        # Stream responses from underlying assistant
        accumulated_content = []
        
        async for response_chunk in self.underlying_assistant.next_message_stream(conversation=conversation, **kwargs):
            # Accumulate content for output guard check
            if hasattr(response_chunk, 'content') and response_chunk.content:
                accumulated_content.append(response_chunk.content)
            
            # Yield the chunk immediately (before output guard check)
            yield response_chunk
        
        # Check output guard on accumulated content
        if self.output_guard and accumulated_content:
            try:
                full_content = ''.join(accumulated_content)
                await self.output_guard(full_content)
            except GuardrailError as error:
                logging.info(f"Guardrail triggered for output message with content: {full_content[:100]}...")
                # Yield an error response as the final chunk
                yield AssistantResponse(content=f"\n\n[Content filtered: {error.message}]")
