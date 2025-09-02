import json
import logging
from typing import Dict, Optional, Tuple

from channels.http import AsyncHttpConsumer
from django.http import HttpResponse

from .config import get_or_raise_config, SAMY_EMP, LLMHUB
from .llm_setup import setup_llmhub_connection
from .vector_db import drop_and_resetup_vector_db
from .assistants import get_guarded_yara_samy_assistant, GuardedAssistant
from .serializers import RAGRequestSerializer
from .types import AVAILABLE_LANGUAGES_TYPE, MessageRole, XBotMode
from .utils import convert_to_RT_format, should_avoid_guardrails
from .models import Conversation


class AppInitializer:
    """Handles application initialization and setup."""
    
    def __init__(self):
        self.config_handler = None
        self.assistants: Dict[AVAILABLE_LANGUAGES_TYPE, GuardedAssistant] = {}
    
    def initialize(self) -> None:
        """Initialize the application components."""
        logging.basicConfig(level=logging.INFO)
        
        self.config_handler = get_or_raise_config(SAMY_EMP)
        self._setup_llm_connection()
        self._setup_vector_db()
        self._initialize_assistants()
        self._load_cached_properties()
    
    def _setup_llm_connection(self) -> None:
        """Set up LLM connection if required."""
        if self.config_handler.get_config("llm_model")["service"] == LLMHUB:
            setup_llmhub_connection(project_name=SAMY_EMP)
    
    def _setup_vector_db(self) -> None:
        """Set up vector database if localhost is detected."""
        vector_db_config = self.config_handler.get_config("vector_db")
        if "localhost" in vector_db_config["db_host"]:
            drop_and_resetup_vector_db(vector_db_config)
    
    def _initialize_assistants(self) -> None:
        """Initialize assistants for all configured languages."""
        languages = self.config_handler.get_config("languages")
        self.assistants = {
            lang: get_guarded_yara_samy_assistant(language=lang) 
            for lang in languages
        }
    
    def _load_cached_properties(self) -> None:
        """Load cached properties for all assistants."""
        for assistant in self.assistants.values():
            assistant.underlying_assistant.load_cached_properties()


class RequestValidator:
    """Handles request validation and header processing."""
    
    @staticmethod
    def validate_request_data(body: bytes) -> Tuple[bool, Optional[dict], Optional[str]]:
        """
        Validate request data.
        
        Returns:
            Tuple of (is_valid, validated_data, error_message)
        """
        try:
            request_data = json.loads(body.decode("utf-8"))
            serializer = RAGRequestSerializer(data=request_data)
            
            if not serializer.is_valid():
                return False, None, json.dumps({"error": serializer.errors})
            
            return True, serializer.validated_data, None
            
        except json.JSONDecodeError as e:
            return False, None, json.dumps({"error": f"Invalid JSON: {str(e)}"})
        except Exception as e:
            return False, None, json.dumps({"error": f"Validation error: {str(e)}"})
    
    @staticmethod
    def extract_and_validate_headers(headers) -> Tuple[bool, Optional[dict], Optional[str]]:
        """
        Extract and validate headers.
        
        Returns:
            Tuple of (is_valid, headers_dict, error_message)
        """
        try:
            decoded_headers = {
                key.decode("utf-8"): value.decode("utf-8") 
                for key, value in headers
            }
            
            language = decoded_headers.get("language")
            if not language or language not in AVAILABLE_LANGUAGES_TYPE.__args__:
                return False, None, json.dumps({
                    "error": "Language is missing or unsupported. Supported languages are nl and fr"
                })
            
            x_bot_mode = decoded_headers.get("x-bot-mode", XBotMode.default)
            
            return True, {
                "language": language,
                "x_bot_mode": x_bot_mode
            }, None
            
        except Exception as e:
            return False, None, json.dumps({"error": f"Header validation error: {str(e)}"})


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
    """
    An asynchronous HTTP consumer for handling RAG (Retrieval-Augmented Generation) answers.
    
    This consumer processes RAG requests, validates input, selects appropriate assistants
    based on language, and streams responses back to the client.
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
