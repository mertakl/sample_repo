	...rest
	async def stream_assistant_response(
            self,
            assistant: GuardedAssistant,
            conversation: Conversation,
            x_bot_mode: str,
            user_query: str
    ) -> None:
        """Stream the assistant response."""
        try:
            stream_generator = self._get_stream_generator(
                assistant, conversation, x_bot_mode, user_query
            )

            async for output in stream_generator:
                response_chunk = json.dumps(output.model_dump()).encode("utf-8") + b"\n"
                await self.consumer.send_body(response_chunk, more_body=True)

            await self.consumer.send_body(b"", more_body=False)

        except Exception as e:
            logging.error(f"Error streaming response: {str(e)}")
            raise
			
    def _get_stream_generator(
            self,
            assistant: GuardedAssistant,
            conversation: Conversation,
            x_bot_mode: str,
            user_query: str
    ):
        """Get the appropriate stream generator based on bot mode."""
        if x_bot_mode == XBotMode.no_guardrails or should_avoid_guardrails(user_query):
            return assistant.underlying_assistant.next_message_stream(
                conversation, user_id="user_id"
            )
        elif x_bot_mode == XBotMode.default:
            return assistant.next_message_stream(conversation, user_id="user_id")
        else:
            raise ValueError(f"Invalid X Bot Mode: {x_bot_mode}")

---------------------


class GuardedAssistant(Assistant):
    """Assistant with input and output guardrail."""

    underlying_assistant: Assistant
    input_guard: Callable[[str], Awaitable[None]] = None
    output_guard: Callable[[str], Awaitable[None]] = None

    async def next_message(self, conversation: Conversation, **kwargs) -> AssistantResponse:
        """Generate YaraSamyResponse - not implemented."""
        raise NotImplementedError("Use next_message_stream for streaming responses")

    async def next_message_stream(self, conversation: Conversation, **kwargs) -> AsyncGenerator[YaraSamyResponse, None]:
        """Streaming version with guardrails applied."""
        assert len(conversation.messages) > 0
        last_message = conversation.messages[-1]
        assert isinstance(last_message, UserMessage), "The conversation should end with a UserMessage"

        # Apply input guard first
        if self.input_guard:
            try:
                await self.input_guard(last_message.string_content)
            except GuardrailError as error:
                logging.info(f"Guardrail triggered for input message {last_message}")
                yield YaraSamyResponse(
                    response=Message(role=MessageRole.ASSISTANT, content=error.message)
                )
                return

        # Stream from underlying assistant
        accumulated_content = ""
        final_response = None

        try:
		##This bloc throws error
            async for response in self.underlying_assistant.next_message_stream(conversation=conversation, **kwargs):
                # Accumulate content for output guard validation
                if response.message and response.message.content:
                    accumulated_content += response.message.content
                # Store the final response for metadata
                final_response = response
                # Yield the response (we'll validate after streaming completes)
                yield response

        except Exception as e:
            logging.error(f"Error in underlying assistant streaming: {str(e)}")
            yield YaraSamyResponse(
                response=Message(role=MessageRole.ASSISTANT, content="An error occurred while processing your request.")
            )
            return

        # Apply output guard on accumulated content
        if self.output_guard and accumulated_content:
            try:
                await self.output_guard(accumulated_content)
            except GuardrailError as error:
                logging.info(f"Guardrail triggered for output message")
                # Send a replacement message indicating guardrail trigger
                yield YaraSamyResponse(
                    response=Message(role=MessageRole.ASSISTANT, content=error.message),
                    metadata=Metadata(
                        confidence_score=None,
                        prompt=None,
                        keyword_search=None,
                        references=None,
                    ) if final_response and final_response.metadata else None
                )
				
				
-----------------------
class YaraSamyAssistant(Assistant, arbitrary_types_allowed=True):
	...rest of the code
	
    async def next_message_stream(self, conversation: Conversation, user_id: str) -> AsyncGenerator[
        YaraSamyResponse, None]:
        """Generate streaming response based on query type.

        Handles three types of queries:
        1. NOTA queries - return matching documents
        2. @doc queries - return document links without LLM processing
        3. Regular queries - full RAG with LLM response

        Args:
            conversation: Chat history between user and assistant
            user_id: User identifier for SSO filtering

        Yields:
            YaraSamyResponse: Streaming response objects
        """
        query = self._validate_and_extract_query(conversation, user_id)

        # Handle empty input
        if not query.content.strip():
            yield self._create_empty_input_response()
            return

        # Handle NOTA queries
        if is_nota(query.content.strip()):
            yield self._create_nota_response(query.content.strip())
            return

        # Handle @doc queries
        if is_at_doc(query.content):
            async for response in self._handle_doc_query(conversation, query):
                yield response
            return

        # Handle regular LLM queries
        async for response in self.generate_llm_answer_stream(conversation, user_id):
            yield response
			
		
	async def generate_llm_answer_stream(
            self,
            conversation: Conversation,
            user_id: str
    ) -> AsyncGenerator[YaraSamyResponse, None]:
        """Generate LLM-powered response with confidence scoring.

        Args:
            conversation: Chat history
            user_id: User identifier

        Yields:
            YaraSamyResponse: First the main response, then confidence score update
        """
        # Get enhanced response from conversational assistant
        enhanced_response = await self.conversational_assistant.next_message(
            conversation=conversation,
            user_id=user_id
        )

        # Format response content
        content = self._format_response_content(enhanced_response)

        # Yield main response
        yield YaraSamyResponse(
            response=Message(role=MessageRole.ASSISTANT, content=content)
        )
Can you identify the cause of the error and fix?

"Error in underlying assistant streaming: Cannot instantiate typing.Union"
