##I need to update the following code;

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

    async def next_message_stream(self, conversation: Conversation, **kwargs) -> StreamingAssistantResponse:
        """Streaming version of next_message."""
        raise NotImplementedError
		
##To be able to use updated assisteant.

class YaraSamyAssistant(Assistant, arbitrary_types_allowed=True):
    """Yara for Samy Assistant - handles various query types including NOTA, @doc, and LLM responses."""

    config_handler: ConfigHandler
    language: AVAILABLE_LANGUAGES_TYPE

    @cached_property
    def nota_url_mapping(self) -> dict[str, list[str]]:
        """Nota URL mapping given the language and configuration."""
        return load_nota_url_from_cos(
            language=self.language,
            config_handler=self.config_handler
        )

    @cached_property
    def conversational_assistant(self) -> FortisConversationalAssistant:
        """Underlying conversational assistant."""
        return get_conversational_assistant(
            config_handler=self.config_handler,
            language=self.language
        )

    @cached_property
    def llm_confidence_score(self) -> LanguageModel:
        """LanguageModel for confidence score."""
        llm_config = self.config_handler.get_config("evaluation_llm_model")
        return get_language_model_from_service(
            service=llm_config["service"],
            model_name=llm_config["name"],
            rpm=llm_config.get("rpm_limit")
        )

    def load_cached_properties(self):
        """Computes cached properties."""
        logging.info("%s nota mappings loaded.", len(self.nota_url_mapping.keys()))
        logging.info("Loaded underlying %s", type(self.conversational_assistant).__name__)
        logging.info("Loaded underlying %s", type(self.llm_confidence_score).__name__)

    async def next_message(self, conversation: Conversation, user_id: str) -> YaraSamyResponse:
        """Generate YaraSamyResponse - not implemented."""
        raise NotImplementedError("Use next_message_stream for streaming responses")

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

    def _validate_and_extract_query(self, conversation: Conversation, user_id: str) -> UserMessage:
        """Validate inputs and extract the user query."""
        if not user_id:
            raise ValueError("user_id is required")

        query = conversation.messages[-1]
        if not isinstance(query, UserMessage):
            raise TypeError("Last message must be a UserMessage")

        return query

    def _create_empty_input_response(self) -> YaraSamyResponse:
        """Create response for empty input."""
        content = self.config_handler.get_config("empty_input_message")[self.language]
        return YaraSamyResponse(
            message=Message(role=MessageRole.ASSISTANT, content=content)
        )

    def _create_nota_response(self, nota_query: str) -> YaraSamyResponse:
        """Create response for NOTA queries."""
        content = pretty_nota_search(
            nota=nota_query,
            nota_url_mapping=self.nota_url_mapping
        )
        return YaraSamyResponse(
            message=Message(role=MessageRole.ASSISTANT, content=content)
        )

    async def _handle_doc_query(
            self,
            conversation: Conversation,
            query: UserMessage
    ) -> AsyncGenerator[YaraSamyResponse, None]:
        """Handle @doc functionality queries."""
        content = strip_at_doc(message=query.content)

        if not content.strip():
            yield self._create_empty_doc_response()
            return

        # Update conversation with stripped content
        updated_conversation = self._update_conversation_with_stripped_content(
            conversation, query, content
        )

        # Get document URLs
        _, retrieval_result = await self.conversational_assistant.retrieval_result(
            conversation_window=self.conversational_assistant.get_conversation_window(
                conversation=updated_conversation
            )
        )

        doc_urls = [
            query_response.chunk.metadata.get("urls", ["No URL found for this document."])
            for query_response in retrieval_result
        ]

        response_content = pretty_at_doc(doc_urls)

        yield YaraSamyResponse(
            message=Message(role=MessageRole.ASSISTANT, content=response_content),
        )

    def _create_empty_doc_response(self) -> YaraSamyResponse:
        """Create response for empty @doc input."""
        content = self.config_handler.get_config("empty_doc_input_message")[self.language]
        return YaraSamyResponse(
            message=Message(role=MessageRole.ASSISTANT, content=content)
        )

    def _update_conversation_with_stripped_content(
            self,
            conversation: Conversation,
            query: UserMessage,
            content: str
    ) -> Conversation:
        """Create updated conversation with stripped @doc content."""
        updated_conversation = conversation.copy()
        updated_conversation.messages[-1] = UserMessage(content=content, id=query.id)
        return updated_conversation

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
            message=Message(role=MessageRole.ASSISTANT, content=content)
        )

        # Calculate and yield confidence score for non-keyword searches
        if not enhanced_response.keyword_search:
            confidence_score = await self._calculate_confidence_score(
                question=conversation.messages[-1].content,
                references=enhanced_response.references,
                answer=content
            )

            yield YaraSamyResponse(
                metadata=Metadata(
                    confidence_score=confidence_score,
                    prompt=enhanced_response.prompt,
                    keyword_search=enhanced_response.keyword_search,
                    references=enhanced_response.references,
                )
            )

    def _format_response_content(self, enhanced_response) -> str:
        """Format the response content based on search type."""
        retriever_config = self.config_handler.get_config("retriever")

        if enhanced_response.keyword_search:
            return "\n".join([
                retriever_config["keyword_detected"][self.language],
                enhanced_response.content,
            ])
        else:
            return "\n".join([
                enhanced_response.content,
                retriever_config["further_detail_message"][self.language],
            ])

    async def _calculate_confidence_score(
            self,
            question: str,
            references,
            answer: str
    ) -> float:
        """Calculate confidence score for the response."""
        return await build_confidence_score(
            question=question,
            references=references,
            answer=answer,
            config_handler=self.config_handler,
            language=self.language,
            llm=self.llm_confidence_score,
        )
		
##Instead of using next_message GuardedAssistant should use next_message_stream
