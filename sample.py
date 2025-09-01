##In the following code'
from channels.generic.http import AsyncHttpConsumer
...rest of the imports


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

           ...rest of the code
            #### SELECT APPROPRIATE ASSISTANT
            assistant = assistants[language]
            messages = [convert_to_RT_format(msg) for msg in request_messages if msg.get("role") != MessageRole.SYSTEM]
            conversation = Conversation(messages=messages)
            user_query = conversation.messages[-1].content

            #### GET THE RESPONSE
            if x_bot_mode == XBotMode.no_guardrails or should_avoid_guardrails(user_query=user_query):
                samy_output: SamyOutput = await assistant.underlying_assistant.next_message(conversation,
                                                                                            user_id="user_id")
            elif x_bot_mode == XBotMode.default:
                samy_output: SamyOutput = await assistant.next_message(conversation, user_id="user_id")
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

            if isinstance(samy_output, SamyOutput):
                response_data = create_yara_samy_response(samy_output)
            else:
                response_data = samy_output

            await self.send_body(json.dumps(response_data.model_dump()).encode("utf-8"), more_body=True)
            await self.send_body(b"", more_body=False)

        except Exception as e:
            error_msg = json.dumps({"error": str(e)})
            await self.send_response(500, error_msg.encode("utf-8"), content_type="application/json")
			

def create_yara_samy_response(samy_output: SamyOutput) -> YaraSamyResponse:
    """Creates the Yara Samy Response for the API."""
    metadata = Metadata(
        confidence_score=samy_output.confidence_score,
        prompt=samy_output.prompt,
        keyword_search=samy_output.keyword_search,
        references=samy_output.references,
    )
    response = Message(role=MessageRole.ASSISTANT, content=samy_output.content),
    yara_samy_response = YaraSamyResponse(
        response=response,
        metadata=metadata
    )

    logger.info("\n response: " + type(response).__name__)
    logger.info("\n Metadata: " + type(metadata).__name__)
    logger.info("\n confidence_score: " + type(metadata.confidence_score).__name__)
    logger.info("\n prompt: " + type(metadata.prompt).__name__)
    logger.info("\n keyword_search: " + type(metadata.keyword_search).__name__)
    logger.info("\n references: " + type(metadata.references).__name__)

    return yara_samy_response
	
	
------asistant.py

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
	
##So basically, what I want to do is 

##I want to modify the RagAnswerConsumer

##so that it returns the response in 2 main packets 

##Note: 
##1. The current endpoint returns the complete response and contains 2 main blocks - "response" and "metadata"
##Or any other way to prevent waiting for confidence_score as it takes too much time
