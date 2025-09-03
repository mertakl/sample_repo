# consumers.py

import json
import logging

from channels.generic.http import AsyncHttpConsumer

# Assuming these are defined in your project
from yara_samy.api.serializers import RAGRequestSerializer
from yara_samy.assistant import get_guarded_yara_samy_assistant
from yara_samy.config import SAMY_EMP, get_or_raise_config
from yara_samy.constants import LLMHUB, AVAILABLE_LANGUAGES_TYPE, XBotMode
from yara_samy.llmhub import setup_llmhub_connection
from yara_samy.utils import GuardedAssistant
from yara_samy.utils_vector_db import drop_and_resetup_vector_db
from yara_samy.utils_rt import convert_to_RT_format
from yara_samy.utils_conv import should_avoid_guardrails
from fortis.conversation.message import Conversation, MessageRole


# --- Global setup code from your original file ---
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
    """An asynchronous HTTP consumer for handling streaming RAG answers."""

    async def handle(self, body):
        """Handle incoming HTTP requests and streams back the response."""
        try:
            # GET AND VALIDATE REQUEST DATA
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

            # CREATE ASSISTANT AND CONVERSATION
            assistant = assistants[language]
            messages = [convert_to_RT_format(msg) for msg in request_messages if msg.get("role") != MessageRole.SYSTEM]
            conversation = Conversation(messages=messages)
            user_query = conversation.messages[-1].content

            # GET THE STREAMING RESPONSE GENERATOR
            stream_generator = None
            if x_bot_mode == XBotMode.no_guardrails or should_avoid_guardrails(user_query=user_query):
                stream_generator = assistant.underlying_assistant.next_message_stream(conversation, user_id="user_id")
            elif x_bot_mode == XBotMode.default:
                stream_generator = assistant.next_message_stream(conversation, user_id="user_id")
            else:
                raise ValueError(f"X Bot Mode {x_bot_mode} is not valid.")

            # PREPARE AND SEND STREAMED RESPONSE
            await self.send_headers(
                headers=[
                    (b"Content-Type", b"text/event-stream"),
                    (b"Cache-Control", b"no-cache"),
                    (b"Connection", b"keep-alive"),
                    (b"X-Accel-Buffering", b"no"), # Helps prevent buffering by reverse proxies like Nginx
                ]
            )

            # Stream the response using Server-Sent Events (SSE)
            async for chunk in stream_generator:
                sse_event = f"data: {json.dumps(chunk)}\n\n"
                await self.send_body(sse_event.encode("utf-8"), more_body=True)

            # Close the connection once the stream is finished
            await self.send_body(b"", more_body=False)

        except Exception as e:
            logging.error(f"An error occurred in RagAnswerConsumer: {e}", exc_info=True)
            # This response may not be sent if headers are already sent, but it's a good fallback.
            error_msg = json.dumps({"error": "An internal server error occurred."})
            await self.send_response(500, error_msg.encode("utf-8"), content_type="application/json")
