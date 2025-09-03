##In the following code;
----consumers,py


logging.basicConfig(level=logging.INFO)
config_handler = get_or_raise_config(SAMY_EMP)
if config_handler.get_config("llm_model")["service"] == LLMHUB:
    setup_llmhub_connection(project_name=SAMY_EMP)
if "localhost" in config_handler.get_config("vector_db")["db_host"]:
    drop_and_resetup_vector_db(config_handler.get_config("vector_db"))
assistants: dict[AVAILABLE_LANGUAGES_TYPE, GuardedAssistant] = {
    lang: get_guarded_yara_samy_assistant(language=lang) for lang in config_handler.get_config("languages")
}
for lang in config_handler.get_config("languages"):
    assistants[lang].underlying_assistant.load_cached_properties()


class RagAnswerConsumer(AsyncHttpConsumer):
    """An asynchronous HTTP consumer for handling RAG (Retrieval-Augmented Generation) answers.

    This consumer waits for a specified amount of time before sending a response.
    It is designed to be used with Django Channels to handle HTTP requests asynchronously.

    Attributes:
        None
    """

    async def handle(self, body):
        """Handle incoming HTTP requests.

        This method is called when an HTTP request is received. It waits for 3 seconds
        before sending a response with the content "This is the rag answer consumer".

        Args:
            body (bytes): The body of the incoming HTTP request.

        Returns:
            None
        """
        try:

            #### GET AND VALIDATE REQUEST DATA
            request_data = json.loads(body.decode("utf-8"))
            serializer = RAGRequestSerializer(data=request_data)
            if not serializer.is_valid():
                await self.send_response(
                    400, json.dumps({"error": serializer.errors}).encode("utf-8"), content_type="application/json"
                )
                return
            validated = serializer.validated_data
            request_messages = validated["messages"]

            headers = dict(self.scope["headers"])
            language = headers.get(b"language", b"fr").decode("utf-8")
            x_bot_mode = headers.get(b"x-bot-mode", XBotMode.default.encode("utf-8")).decode("utf-8")

            logging.debug("Mode: %s", x_bot_mode)

            #### CREATE ASSISTANT
            assistant = assistants[language]
            messages = [convert_to_RT_format(msg) for msg in request_messages if msg.get("role") != MessageRole.SYSTEM]
            conversation = Conversation(messages=messages)
            user_query = conversation.messages[-1].content

            #### GET THE RESPONSE
            if x_bot_mode == XBotMode.no_guardrails or should_avoid_guardrails(user_query=user_query):
                samy_output = await assistant.underlying_assistant.next_message(conversation, user_id="user_id")
            elif x_bot_mode == XBotMode.default:
                samy_output = await assistant.next_message(conversation, user_id="user_id")
            else:
                raise ValueError(f"X Bot Mode {x_bot_mode} is not valid.")

            #### PREPARE AND SEND REPONSE
            await self.send_headers(
                headers=[
                    (b"Content-Type", b"text/event-stream"),
                    (b"Cache-Control", b"no-cache"),
                    (b"Connection", b"keep-alive"),
                ]
            )

            response_data = create_yara_samy_response(samy_output)

            await self.send_body(json.dumps(response_data.model_dump()).encode("utf-8"), more_body=True)
            await self.send_body(b"", more_body=False)

        except Exception as e:
            error_msg = json.dumps({"error": str(e)})
            await self.send_response(500, error_msg.encode("utf-8"), content_type="application/json")
			
-----utils.py
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

    async def next_message_stream(self, conversation: Conversation) -> StreamingAssistantResponse:
        """Streaming version of next_message."""
        raise NotImplementedError
		
---assistant.py
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
	
##I need to implement stream version of YaraSamyAssistant and GuardedAssistant. You should also keep the non streamed version. Can you do that for me? 
Also refactor according to best practices. RagAnswerConsumer should use streamed version
