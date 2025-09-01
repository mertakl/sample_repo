##In this code;

class SamyOutput(EnhancedAssistantResponse):
    """Output of Yara Samy with confidence score."""

    confidence_score: ConfidenceScore | None


class YaraSamyAssistant(Assistant, arbitrary_types_allowed=True):
    """Yara for Samy Assistant."""

    config_handler: ConfigHandler
    language: AVAILABLE_LANGUAGES_TYPE

    @cached_property
    def nota_url_mapping(self) -> dict[str, list[str]]:
        """Nota URL mapping given the language and configuration."""
        return load_nota_url_from_cos(language=self.language, config_handler=self.config_handler)

    @cached_property
    def conversational_assistant(self) -> FortisConversationalAssistant:
        """Underlying conversational assistant."""
        return get_conversational_assistant(config_handler=self.config_handler, language=self.language)

    @cached_property
    def llm_confidence_score(self) -> LanguageModel:
        """LanguageModel for confidence score."""
        llm_config = self.config_handler.get_config("evaluation_llm_model")
        return get_language_model_from_service(
            service=llm_config["service"], model_name=llm_config["name"], rpm=llm_config.get("rpm_limit")
        )

    def load_cached_properties(self):
        """Computes cached properties."""
        logging.info("%s nota mappings loaded.", len(self.nota_url_mapping.keys()))
        logging.info("Loaded underlying %s", type(self.conversational_assistant).__name__)
        logging.info("Loaded underlying %s", type(self.llm_confidence_score).__name__)

    async def next_message(self, conversation: Conversation, user_id: str) -> SamyOutput:  # pylint: disable=W0221
        """Generates SamyOutput."""
        raise NotImplementedError

    async def next_message_stream(self, conversation: Conversation, user_id: str) -> AsyncGenerator[SamyOutput, None]: # pylint: disable=W0221
        """Generates a streaming response for all cases (nota, @doc, and LLM answers).

        Args:
            conversation: conversation history of user and assistant
            user_id: ID of the user for SSO filtering

        Yields:
            SamyOutput: Streaming SamyOutput objects
        """
        query = conversation.messages[-1]
        assert isinstance(query, UserMessage)
        # For now, we don't use user_id. It's a placeholder for SSO information.
        assert user_id, "user_id is not given."

        if not query.content.strip():
            # The input is empty - yield single response
            content = self.config_handler.get_config("empty_input_message")[self.language]
            yield SamyOutput(
                prompt=None,
                keyword_search=None,
                references=None,
                content=content,
                confidence_score=None,
            )
            return

        # When a user asks a question with just a nota, we return the docs matching to that nota
        if is_nota(query.content.strip()):
            content = pretty_nota_search(nota=query.content.strip(), nota_url_mapping=self.nota_url_mapping)
            yield SamyOutput(
                prompt=None,
                keyword_search=None,
                references=None,
                content=content,
                confidence_score=None,
            )
            return

        # When a user uses the @doc functionality, we return links to document without final LLM call
        if is_at_doc(query.content):
            content = strip_at_doc(message=query.content)
            if not content.strip():
                content = self.config_handler.get_config("empty_doc_input_message")[self.language]
                yield SamyOutput(
                    prompt=None,
                    keyword_search=None,
                    references=None,
                    content=content,
                    confidence_score=None,
                )
                return

            # Update the conversation with stripped content
            conversation.messages[-1] = UserMessage(content=content, id=conversation.messages[-1].id)
            _, retrieval_result = await self.conversational_assistant.retrieval_result(
                conversation_window=self.conversational_assistant.get_conversation_window(conversation=conversation)
            )

            content = pretty_at_doc(
                [
                    query_response.chunk.metadata.get("urls", ["No URL found for this document."])
                    for query_response in retrieval_result
                ]
            )

            yield SamyOutput(
                prompt=None,
                keyword_search=None,
                references=None,
                content=content,
                confidence_score=None,
            )
            return

        # Classic RAG question or keyword search that requires an LLM call to generate the answer
        async for samy_output in self.generate_llm_answer_stream(conversation=conversation, user_id=user_id):
            yield samy_output

    async def generate_llm_answer_stream(self, conversation: Conversation, user_id: str) -> AsyncGenerator[SamyOutput, None]:
        """Get the final chat response and references in streaming format.

        Args:
            conversation: conversation history
            user_id: id of the user

        Yields:
            SamyOutput: First yields the response, then yields confidence score separately
        """
        enhanced_assistant_response = await self.conversational_assistant.next_message(
            conversation=conversation, user_id=user_id
        )
        retriever_config = self.config_handler.get_config("retriever")

        # Prepare the content based on keyword_search flag
        if enhanced_assistant_response.keyword_search:
            content = "\n".join(
                [
                    retriever_config["keyword_detected"][self.language],
                    enhanced_assistant_response.content,
                ]
            )
        else:
            content = "\n".join(
                [
                    enhanced_assistant_response.content,
                    retriever_config["further_detail_message"][self.language],
                ]
            )

        # Yield the response immediately (without confidence score)
        yield SamyOutput(
            prompt=enhanced_assistant_response.prompt,
            keyword_search=enhanced_assistant_response.keyword_search,
            references=enhanced_assistant_response.references,
            content=content,
            confidence_score=None,  # Will be sent separately
        )

        # Calculate and yield confidence score
        if not enhanced_assistant_response.keyword_search:
            confidence_score = await build_confidence_score(
                question=conversation.messages[-1].content,
                references=enhanced_assistant_response.references,
                answer=content,
                config_handler=self.config_handler,
                language=self.language,
                llm=self.llm_confidence_score,
            )

            # Yield SamyOutput with the confidence score
            yield SamyOutput(
                prompt=None,  # Already sent in first packet
                keyword_search=None,  # Already sent in first packet
                references=None,  # Already sent in first packet
                content=None,  # Already sent in first packet
                confidence_score=confidence_score,
            )
			
Instead of SamyOutput, I want to return YaraSamyResponse

class Message(ConfiguredBaseModel):
    """Message schema."""

    role: MessageRole
    content: str

    def to_rag_toolbox(self) -> RTMessage:
        """Helper: convert to RAG-Toolbox object."""
        match self.role:
            case MessageRole.SYSTEM:
                return SystemMessage(content=self.content)
            case MessageRole.ASSISTANT:
                return AssistantMessage(content=self.content)
            case MessageRole.USER:
                return UserMessage(content=self.content)
            case _:
                raise NotImplementedError


class Metadata(ConfiguredBaseModel):
    confidence_score: ConfidenceScore
    prompt: Prompt | None
    keyword_search: bool
    references: list[DocumentChunk] | None | None


class YaraSamyResponse(ConfiguredBaseModel):
    """Yara for Samy API Response Schema."""

    message: Message
    metadata: Metadata
