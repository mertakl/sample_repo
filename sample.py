##In the following code;


class EnhancedAssistantResponse(AssistantResponse):
    """AssistantResponse with the prompt."""

    prompt: Prompt | None
    keyword_search: bool | None

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
        """Decides if the question matches a nota or not and answers it accordingly.

        Args:
            conversation: conversation history of user and assistant
            user_id: ID of the user for SSO filtering

        Return:
            Samy Output (sent with API, in the incoming future)
        """
        query = conversation.messages[-1]
        assert isinstance(query, UserMessage)
        # For now, we don't use user_id. It's a placeholder for SSO information.
        assert user_id, "user_id is not given."
        if not query.content.strip():
            # The input is empty
            return SamyOutput(
                prompt=None,
                keyword_search=None,
                references=None,
                content=self.config_handler.get_config("empty_input_message")[self.language],
                confidence_score=None,
            )

        # When a user ask a question with just a nota, we return the docs matching to that nota
        if is_nota(query.content.strip()):
            return SamyOutput(
                prompt=None,
                keyword_search=None,
                references=None,
                content=pretty_nota_search(nota=query.content.strip(), nota_url_mapping=self.nota_url_mapping),
                confidence_score=None,
            )

        # When a user uses the @doc functionality, we return links to document without final LLM call
        if is_at_doc(query.content):
            content = strip_at_doc(message=query.content)
            if not content.strip():
                return SamyOutput(
                    prompt=None,
                    keyword_search=None,
                    references=None,
                    content=self.config_handler.get_config("empty_doc_input_message")[self.language],
                    confidence_score=None,
                )
            conversation.messages[-1] = UserMessage(content=content, id=conversation.messages[-1].id)
            _, retrieval_result = await self.conversational_assistant.retrieval_result(
                conversation_window=self.conversational_assistant.get_conversation_window(conversation=conversation)
            )
            return SamyOutput(
                prompt=None,
                keyword_search=None,
                references=None,
                content=pretty_at_doc(
                    [
                        query_response.chunk.metadata.get("urls", ["No URL found for this document."])
                        for query_response in retrieval_result
                    ]
                ),
                confidence_score=None,
            )

        # Classic RAG question or keyword search that requires an LLM call to generate the answer
        return await self.generate_llm_answer(conversation=conversation, user_id=user_id)

    async def next_message_stream(  # pylint: disable=W0221
        self, conversation: Conversation, user_id: str
    ) -> StreamingAssistantResponse:
        """Generates a streaming response."""
        raise NotImplementedError

    async def generate_llm_answer(self, conversation: Conversation, user_id: str) -> SamyOutput:
        """Get the final chat response and references.

        Args:
            conversation: conversation history
            user_id: id of the user
        Return:
            SamyOutput chat response with associated references, prompt and keyword_search
        """
        enhanced_assistant_response = await self.conversational_assistant.next_message(
            conversation=conversation, user_id=user_id
        )
        retriever_config = self.config_handler.get_config("retriever")

        if enhanced_assistant_response.keyword_search:
            enhanced_assistant_response.content = "\n".join(
                [
                    retriever_config["keyword_detected"][self.language],
                    enhanced_assistant_response.content,
                ]
            )
            confidence_score = None
        else:
            enhanced_assistant_response.content = "\n".join(
                [
                    enhanced_assistant_response.content,
                    retriever_config["further_detail_message"][self.language],
                ]
            )
            confidence_score = await build_confidence_score(
                question=conversation.messages[-1].content,
                references=enhanced_assistant_response.references,
                answer=enhanced_assistant_response.content,
                config_handler=self.config_handler,
                language=self.language,
                llm=self.llm_confidence_score,
            )
        return SamyOutput(**enhanced_assistant_response.dict(), confidence_score=confidence_score)


def get_guarded_yara_samy_assistant(
    language: AVAILABLE_LANGUAGES_TYPE,
) -> Assistant:
    """Returns an Assistant with the default Yara.Samy config given a language."""
    return GuardedAssistant(
        underlying_assistant=YaraSamyAssistant(config_handler=get_or_raise_config(SAMY_EMP), language=language),
        input_guard=UnusualPromptGuardrail().validate,
        output_guard=ClassificationGuardrail().validate,
    )
	
##Instead of using next_message I want to use next_message_stream. I kind of converted the code for generate_llm_answer to return stream but I need to also adapt the other part.
Here is the new streaming generate_llm_answer 

enhanced_assistant_response = await self.conversational_assistant.next_message(
            conversation=conversation, user_id=user_id
        )
        retriever_config = self.config_handler.get_config("retriever")

        # 2. Prepare and YIELD the first packet (the main response)
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

        # Update the content in the response object for later use
        enhanced_assistant_response.content = content

        # Create and yield response
        response_packet = {
            "response": Message(role=MessageRole.ASSISTANT, content=content).model_dump()
        }
        yield response_packet

        # Calculate the confidence score
        confidence_score = None
        if not enhanced_assistant_response.keyword_search:
            confidence_score = await build_confidence_score(
                question=conversation.messages[-1].content,
                references=enhanced_assistant_response.references,
                answer=enhanced_assistant_response.content,
                config_handler=self.config_handler,
                language=self.language,
                llm=self.llm_confidence_score,
            )

        # Prepare and yield metadata
        metadata = Metadata(
            confidence_score=confidence_score,
            prompt=enhanced_assistant_response.prompt,
            keyword_search=enhanced_assistant_response.keyword_search,
            references=enhanced_assistant_response.references,
        )

        metadata_packet = {"metadata": metadata.model_dump()}
        yield metadata_packet
		
##Here is how I tried to use this code. Help me to properly do it. 

 #### SELECT APPROPRIATE ASSISTANT
            assistant = assistants[language]
            messages = [convert_to_RT_format(msg) for msg in request_messages if msg.get("role") != MessageRole.SYSTEM]
            conversation = Conversation(messages=messages)
            user_query = conversation.messages[-1].content

            #### PREPARE AND SEND REPONSE
            await self.send_headers(
                headers=[
                    (b"Content-Type", b"text/event-stream"),
                    (b"Cache-Control", b"no-cache"),
                    (b"Connection", b"keep-alive"),
                ]
            )

            #### GET THE RESPONSE
            if x_bot_mode == XBotMode.no_guardrails or should_avoid_guardrails(user_query=user_query):
                stream_generator = assistant.underlying_assistant.next_message_stream(conversation, user_id="user_id")
            elif x_bot_mode == XBotMode.default:
                stream_generator = assistant.next_message_stream(conversation, user_id="user_id")
            else:
                raise ValueError(f"X Bot Mode {x_bot_mode} is not valid.")

            # Iterate through the async generator and send each packet
            async for packet in stream_generator:
                response_chunk = json.dumps(packet).encode("utf-8") + b"\n"  # NDJSON ends with a newline
                await self.send_body(response_chunk, more_body=True)

            # Close the connection
            await self.send_body(b"", more_body=False)
