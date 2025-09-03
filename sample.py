#In the following code;

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


def get_guarded_yara_samy_assistant(
        language: AVAILABLE_LANGUAGES_TYPE,
) -> Assistant:
    """Returns an Assistant with the default Yara.Samy config given a language."""
    return GuardedAssistant(
        underlying_assistant=YaraSamyAssistant(config_handler=get_or_raise_config(SAMY_EMP), language=language),
        input_guard=UnusualPromptGuardrail().validate,
        output_guard=ClassificationGuardrail().validate,
    )
------------------
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
		
------------------------

class ResponseHandler:
    """Handles response generation and streaming."""

    def __init__(self, consumer: AsyncHttpConsumer):
        self.consumer = consumer

    async def send_error_response(self, status_code: int, error_message: str) -> None:
        """Send an error response."""
        await self.consumer.send_response(
            status_code,
            error_message.encode("utf-8"),
            content_type="application/json"
        )

    async def send_streaming_headers(self) -> None:
        """Send headers for streaming response."""
        await self.consumer.send_headers(
            headers=[
                (b"Content-Type", b"text/event-stream"),
                (b"Cache-Control", b"no-cache"),
                (b"Connection", b"keep-alive"),
            ]
        )

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


# Initialize the application
app_initializer = AppInitializer()
app_initializer.initialize()


class HelloWorld(AsyncHttpConsumer):
    """Index Page to ping the app."""

    async def handle(self, body: bytes) -> None:
        """Handle GET Request."""
        message = "Hello World"
        await self.send_response(
            200,
            message.encode("utf-8"),
            headers=[(b"Content-Type", b"text/plain")]
        )


class RagAnswerConsumer(AsyncHttpConsumer):
    """An asynchronous HTTP consumer for handling RAG (Retrieval-Augmented Generation) answers.

       This consumer waits for a specified amount of time before sending a response.
       It is designed to be used with Django Channels to handle HTTP requests asynchronously.
       """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.response_handler = ResponseHandler(self)
        self.validator = RequestValidator()

    async def handle(self, body: bytes) -> None:
        """
        Handle incoming HTTP requests for RAG answers.

        Args:
            body: The body of the incoming HTTP request.
        """
        try:
            # Validate request data
            is_valid, validated_data, error_msg = self.validator.validate_request_data(body)
            if not is_valid:
                await self.response_handler.send_error_response(400, error_msg)
                return

            # Validate headers
            is_valid, headers_data, error_msg = self.validator.extract_and_validate_headers(
                self.scope["headers"]
            )
            if not is_valid:
                await self.response_handler.send_error_response(400, error_msg)
                return

            # Process the request
            await self._process_rag_request(validated_data, headers_data)

        except Exception as e:
            logging.error(f"Unexpected error in RagAnswerConsumer: {str(e)}")
            error_msg = json.dumps({"error": "Internal server error"})
            await self.response_handler.send_error_response(500, error_msg)

    async def _process_rag_request(self, validated_data: dict, headers_data: dict) -> None:
        """
        Process the RAG request and stream the response.

        Args:
            validated_data: Validated request data
            headers_data: Validated headers data
        """
        request_messages = validated_data["messages"]
        language = headers_data["language"]
        x_bot_mode = headers_data["x_bot_mode"]

        logging.debug("Mode: %s", x_bot_mode)

        # Select appropriate assistant
        assistant = app_initializer.assistants[language]

        # Prepare conversation
        messages = [
            convert_to_RT_format(msg)
            for msg in request_messages
            if msg.get("role") != MessageRole.SYSTEM
        ]
        conversation = Conversation(messages=messages)
        user_query = conversation.messages[-1].content

        # Send streaming headers
        await self.response_handler.send_streaming_headers()

        # Stream the response
        await self.response_handler.stream_assistant_response(
            assistant, conversation, x_bot_mode, user_query
        )
		
### I need to update the GuardedAssistant to use next_message_stream. Also update the following code to use the stream as well


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


# ===== API SETUP =====
app = FastAPI()


@app.get("/")
def read_root():
    """Index."""
    return {"version": "v0.0.1"}


@app.patch("/refresh")
async def refresh() -> bool:
    """Refresh backbone models."""
    llm_config = config_handler.get_config("llm_model")
    model_name = llm_config["name"]
    llm = get_language_model_from_service(
        service=llm_config["service"], model_name=model_name, rpm=llm_config.get("rpm_limit")
    )
    prompt = Prompt(messages=[UserMessage(content="Hi")])
    generation_config = GenerationConfig(temperature=0, max_tokens=10)
    try:
        await llm.generate_answer(prompt=prompt, generation_config=generation_config)
    except Exception:  # pylint: disable=W0718
        return False
    for language, assistant in assistants.items():
        logging.info("Refreshing %s assistant", language)
        assistant.conversational_assistant.llm = llm
    return True


@app.post("/get_response")
async def get_response(
    request: YaraSamyRequest,
    language: Annotated[AVAILABLE_LANGUAGES_TYPE, Header()] = "fr",
    x_bot_mode: Literal[XBotMode.default, XBotMode.no_guardrails] = XBotMode.default,
) -> YaraSamyResponse:
    """Yara.Samy request route."""
    logging.debug("Mode: %s", x_bot_mode)
    assistant = assistants[language]
    conversation = Conversation(
        messages=[msg.to_rag_toolbox() for msg in request.messages if msg.role != MessageRole.SYSTEM]
    )
    user_query = conversation.messages[-1].content
    if x_bot_mode == XBotMode.no_guardrails or should_avoid_guardrails(user_query=user_query):
        samy_output: SamyOutput = await assistant.underlying_assistant.next_message(conversation, user_id="user_id")
    elif x_bot_mode == XBotMode.default:
        samy_output: SamyOutput = await assistant.next_message(conversation, user_id="user_id")
    else:
        raise ValueError(f"X Bot Mode {x_bot_mode} is not valid.")

    # If guardrails act, samy_output is an AssistantResponse, not a SamyOutput
    return YaraSamyResponse(
        response=Message(role=MessageRole.ASSISTANT, content=samy_output.content),
        metadata={
            "confidence_score": samy_output.confidence_score if isinstance(samy_output, SamyOutput) else None,
            "prompt": samy_output.prompt if isinstance(samy_output, SamyOutput) else None,
            "keyword_search": samy_output.keyword_search if isinstance(samy_output, SamyOutput) else None,
            "references": samy_output.references if isinstance(samy_output, SamyOutput) else None,
        }, 
    )
