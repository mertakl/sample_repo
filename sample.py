import json
import logging
from typing import get_args

from channels.generic.http import AsyncHttpConsumer
from your_project.assistants import (
    get_guarded_yara_samy_assistant,
    should_avoid_guardrails,
)
from your_project.config import (
    get_or_raise_config,
    setup_llmhub_connection,
    drop_and_resetup_vector_db,
    SAMY_EMP,
    LLMHUB,
)
from your_project.constants import (
    AVAILABLE_LANGUAGES_TYPE,
    XBotMode,
    MessageRole,
)
from your_project.serializers import RAGRequestSerializer
from your_project.types import Conversation, GuardedAssistant
from your_project.utils import convert_to_RT_format

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def initialize_app_state() -> dict:
    """
    Initializes and returns the application state, including configuration
    and assistants.
    """
    try:
        config_handler = get_or_raise_config(SAMY_EMP)
        app_config = config_handler.get_config()

        # Setup LLM Hub connection if configured
        if app_config.get("llm_model", {}).get("service") == LLMHUB:
            setup_llmhub_connection(project_name=SAMY_EMP)
            logging.info("LLM Hub connection established.")

        # Reset vector database if using a local instance
        vector_db_config = app_config.get("vector_db", {})
        if "localhost" in vector_db_config.get("db_host", ""):
            drop_and_resetup_vector_db(vector_db_config)
            logging.info("Local vector database has been reset.")

        # Initialize assistants for each configured language
        languages = app_config.get("languages", [])
        assistants = {
            lang: get_guarded_yara_samy_assistant(language=lang) for lang in languages
        }
        for lang, assistant in assistants.items():
            assistant.underlying_assistant.load_cached_properties()
            logging.info(f"Loaded cached properties for '{lang}' assistant.")

        return {"assistants": assistants}

    except Exception as e:
        logging.critical(f"Critical error during application initialization: {e}", exc_info=True)
        raise

# Initialize application state globally on startup
APP_STATE = initialize_app_state()

class HelloWorldConsumer(AsyncHttpConsumer):
    """A simple consumer to confirm the application is running."""

    async def handle(self, body: bytes) -> None:
        """Handles the incoming request and returns a hello message."""
        message = b"Hello World - Service is running."
        await self.send_response(
            200,
            message,
            headers=[(b"Content-Type", b"text/plain")],
        )

class RagAnswerConsumer(AsyncHttpConsumer):
    """
    Asynchronous HTTP consumer for handling Retrieval-Augmented Generation (RAG)
    requests and streaming responses.
    """

    async def handle(self, body: bytes) -> None:
        """Main entry point for handling incoming HTTP requests."""
        try:
            request_data, headers = await self._parse_request(body)
            language, x_bot_mode = self._validate_headers(headers)
            validated_data = self._validate_request_data(request_data)

            assistant = APP_STATE["assistants"][language]
            conversation = self._prepare_conversation(validated_data["messages"])

            await self.stream_response(assistant, conversation, x_bot_mode)

        except json.JSONDecodeError:
            await self._send_error_response(400, "Invalid JSON format.")
        except ValueError as e:
            await self._send_error_response(400, str(e))
        except Exception as e:
            logging.error(f"An unexpected error occurred: {e}", exc_info=True)
            await self._send_error_response(500, "An internal server error occurred.")

    async def _parse_request(self, body: bytes) -> tuple[dict, dict]:
        """Parses the request body and headers."""
        request_data = json.loads(body.decode("utf-8"))
        headers = {key.decode("utf-8").lower(): value.decode("utf-8") for key, value in self.scope["headers"]}
        return request_data, headers

    def _validate_headers(self, headers: dict) -> tuple[str, str]:
        """Validates required headers and returns them."""
        language = headers.get("language")
        if language not in get_args(AVAILABLE_LANGUAGES_TYPE):
            raise ValueError("Language header is missing, invalid, or unsupported.")

        x_bot_mode = headers.get("x-bot-mode", XBotMode.default)
        if x_bot_mode not in (XBotMode.default, XBotMode.no_guardrails):
            raise ValueError(f"The 'x-bot-mode' header value '{x_bot_mode}' is not valid.")

        logging.debug(f"Request Mode: {x_bot_mode}")
        return language, x_bot_mode

    def _validate_request_data(self, request_data: dict) -> dict:
        """Validates the request payload using a serializer."""
        serializer = RAGRequestSerializer(data=request_data)
        if not serializer.is_valid():
            raise ValueError(json.dumps(serializer.errors))
        return serializer.validated_data

    def _prepare_conversation(self, messages: list[dict]) -> Conversation:
        """Prepares the conversation object from request messages."""
        rt_messages = [
            convert_to_RT_format(msg)
            for msg in messages
            if msg.get("role") != MessageRole.SYSTEM
        ]
        if not rt_messages:
            raise ValueError("Conversation must contain at least one user message.")
        return Conversation(messages=rt_messages)

    async def stream_response(self, assistant: GuardedAssistant, conversation: Conversation, x_bot_mode: str) -> None:
        """Streams the assistant's response back to the client."""
        await self.send_headers(
            headers=[
                (b"Content-Type", b"text/event-stream"),
                (b"Cache-Control", b"no-cache"),
                (b"Connection", b"keep-alive"),
                (b"X-Content-Type-Options", b"nosniff"),
            ]
        )

        user_query = conversation.messages[-1].content
        use_guardrails = x_bot_mode == XBotMode.default and not should_avoid_guardrails(user_query=user_query)

        stream_generator = (
            assistant.next_message_stream(conversation, user_id="user_id")
            if use_guardrails
            else assistant.underlying_assistant.next_message_stream(conversation, user_id="user_id")
        )

        async for output in stream_generator:
            response_chunk = f"data: {json.dumps(output.model_dump())}\n\n".encode("utf-8")
            await self.send_body(response_chunk, more_body=True)

        # Signal the end of the stream
        await self.send_body(b"", more_body=False)

    async def _send_error_response(self, status_code: int, error_message: str) -> None:
        """Sends a standardized JSON error response."""
        error_payload = json.dumps({"error": error_message}).encode("utf-8")
        await self.send_response(
            status_code,
            error_payload,
            headers=[(b"Content-Type", b"application/json")],
        )
