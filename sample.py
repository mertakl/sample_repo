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


class HelloWorld(AsyncHttpConsumer):
    """Index Page to ping the app."""

    async def handle(self, body):
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

            decoded_headers = {key.decode("utf-8"): value.decode("utf-8") for key, value in self.scope["headers"]}
            try:
                language_value = decoded_headers.get("language")
                if language_value not in get_args(AVAILABLE_LANGUAGES_TYPE):
                    raise Exception
            except Exception:
                await self.send_response(
                    400,
                    json.dumps(
                        {
                            "error": "Language is missing OR contains an unsupported Language. Supported Languages are nl and fr"
                        }
                    ).encode("utf-8"),
                    content_type="application/json",
                )
                return
            language = decoded_headers.get("language", "fr")
            x_bot_mode = decoded_headers.get("x-bot-mode", XBotMode.default)

            logging.debug("Mode: %s", x_bot_mode)

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
            async for output in stream_generator:
                response_chunk = json.dumps(output.model_dump()).encode("utf-8") + b"\n"  # NDJSON ends with a newline
                await self.send_body(response_chunk, more_body=True)

            # Close the connection
            await self.send_body(b"", more_body=False)

        except Exception as e:
            error_msg = json.dumps({"error": str(e)})
            await self.send_response(500, error_msg.encode("utf-8"), content_type="application/json")
