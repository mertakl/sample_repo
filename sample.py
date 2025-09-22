import json
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from django.test import TestCase
from channels.testing import HttpCommunicator
from channels.db import database_sync_to_async
import logging
import sys

# SOLUTION 1: Mock before importing the module
def setup_module():
    """Set up module-level mocks before importing consumers."""
    # Mock all external dependencies before importing
    mock_modules = {
        'consumers.get_or_raise_config': Mock(),
        'consumers.setup_llmhub_connection': Mock(),
        'consumers.drop_and_resetup_vector_db': Mock(),
        'consumers.get_guarded_yara_samy_assistant': Mock(),
        'consumers.RAGRequestSerializer': Mock(),
        'consumers.AVAILABLE_LANGUAGES_TYPE': Mock(),
        'consumers.XBotMode': Mock(),
        'consumers.should_avoid_guardrails': Mock(),
        'consumers.Conversation': Mock(),
        'consumers.convert_to_RT_format': Mock(),
        'consumers.MessageRole': Mock(),
        'consumers.LLMHUB': 'LLMHUB',
        'consumers.SAMY_EMP': 'SAMY_EMP',
    }
    
    # Apply patches
    for module_path, mock_obj in mock_modules.items():
        patch(module_path, mock_obj).start()

# Call setup before importing
setup_module()

# Now import your consumers - the initialization will use mocked dependencies
from consumers import (
    ResponseHandler,
    RequestValidator,
    AppInitializer,
    HelloWorld,
    RagAnswerConsumer,
    app_initializer  # This will be properly mocked now
)


class TestResponseHandler(TestCase):
    """Test cases for ResponseHandler class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_consumer = AsyncMock()
        self.response_handler = ResponseHandler(self.mock_consumer)
    
    async def test_send_error_response(self):
        """Test sending error response."""
        status_code = 400
        error_message = "Bad Request"
        
        await self.response_handler.send_error_response(status_code, error_message)
        
        self.mock_consumer.send_response.assert_called_once_with(
            status_code,
            error_message.encode("utf-8"),
            headers={"Content-Type", "application/json"}
        )
    
    async def test_send_streaming_headers(self):
        """Test sending streaming headers."""
        await self.response_handler.send_streaming_headers()
        
        expected_headers = [
            ("Content-Type", "text/event-stream"),
            ("Cache-Control", "no-cache"),
            ("Connection", "keep-alive"),
        ]
        self.mock_consumer.send_headers.assert_called_once_with(expected_headers)
    
    @patch('consumers.json.dumps')
    async def test_stream_assistant_response_success(self, mock_json_dumps):
        """Test successful streaming of assistant response."""
        # Mock dependencies
        mock_assistant = Mock()
        mock_conversation = Mock()
        mock_output = Mock()
        mock_output.model_dump.return_value = {"content": "test response"}
        mock_json_dumps.return_value = '{"content": "test response"}'
        
        with patch.object(self.response_handler, '_get_stream_generator') as mock_get_generator:
            mock_get_generator.return_value = [mock_output]
            
            await self.response_handler.stream_assistant_response(
                mock_assistant, mock_conversation, "default", "test query"
            )
            
            # Verify stream generator was called
            mock_get_generator.assert_called_once_with(
                mock_assistant, mock_conversation, "default", "test query"
            )
            
            # Verify response was sent
            self.mock_consumer.send_body.assert_any_call(
                b'data: {"content": "test response"}\\n\\n',
                more_body=True
            )
            self.mock_consumer.send_body.assert_called_with(b"", more_body=False)
    
    @patch('consumers.logging.error')
    async def test_stream_assistant_response_exception(self, mock_log_error):
        """Test exception handling in stream_assistant_response."""
        mock_assistant = Mock()
        mock_conversation = Mock()
        
        with patch.object(self.response_handler, '_get_stream_generator') as mock_get_generator:
            mock_get_generator.side_effect = Exception("Test error")
            
            with pytest.raises(Exception, match="Test error"):
                await self.response_handler.stream_assistant_response(
                    mock_assistant, mock_conversation, "default", "test query"
                )
            
            mock_log_error.assert_called_once()
    
    @patch('consumers.should_avoid_guardrails')
    @patch('consumers.XBotMode')
    def test_get_stream_generator_no_guardrails(self, mock_xbot_mode, mock_should_avoid):
        """Test stream generator selection for no guardrails mode."""
        mock_xbot_mode.no_guardrails = "no_guardrails"
        mock_should_avoid.return_value = True
        
        mock_assistant = Mock()
        mock_conversation = Mock()
        
        result = self.response_handler._get_stream_generator(
            mock_assistant, mock_conversation, "no_guardrails", "test query"
        )
        
        mock_assistant.next_message_stream.assert_called_once_with(
            mock_conversation, user_id="user_id"
        )
    
    def test_get_stream_generator_invalid_mode(self):
        """Test exception for invalid bot mode."""
        mock_assistant = Mock()
        mock_conversation = Mock()
        
        with pytest.raises(ValueError, match="Invalid X Bot Mode"):
            self.response_handler._get_stream_generator(
                mock_assistant, mock_conversation, "invalid_mode", "test query"
            )


class TestRequestValidator(TestCase):
    """Test cases for RequestValidator class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.validator = RequestValidator()
    
    @patch('consumers.RAGRequestSerializer')
    def test_validate_request_data_success(self, mock_serializer_class):
        """Test successful request data validation."""
        mock_serializer = Mock()
        mock_serializer.is_valid.return_value = True
        mock_serializer.validated_data = {"messages": []}
        mock_serializer_class.return_value = mock_serializer
        
        body = json.dumps({"messages": []}).encode("utf-8")
        
        is_valid, validated_data, error_msg = self.validator.validate_request_data(body)
        
        self.assertTrue(is_valid)
        self.assertEqual(validated_data, {"messages": []})
        self.assertIsNone(error_msg)
    
    def test_validate_request_data_json_decode_error(self):
        """Test JSON decode error handling."""
        body = b"invalid json"
        
        is_valid, validated_data, error_msg = self.validator.validate_request_data(body)
        
        self.assertFalse(is_valid)
        self.assertIsNone(validated_data)
        self.assertIn("Invalid JSON", json.loads(error_msg)["error"])
    
    @patch('consumers.AVAILABLE_LANGUAGES_TYPE')
    @patch('consumers.XBotMode')
    def test_extract_and_validate_headers_success(self, mock_xbot_mode, mock_available_languages):
        """Test successful header validation."""
        mock_available_languages.__args__ = ["en", "fr"]
        mock_xbot_mode.default = "default"
        
        headers = [
            (b"language", b"en"),
            (b"x-bot-mode", b"default")
        ]
        
        is_valid, headers_data, error_msg = self.validator.extract_and_validate_headers(headers)
        
        self.assertTrue(is_valid)
        self.assertEqual(headers_data, {"language": "en", "x_bot_mode": "default"})
        self.assertIsNone(error_msg)


class TestAppInitializer(TestCase):
    """Test cases for AppInitializer class - testing individual methods."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create a fresh instance that won't run initialize() automatically
        self.app_initializer = AppInitializer()
        self.app_initializer.config_handler = None
        self.app_initializer.assistants = {}
    
    @patch('consumers.logging.basicConfig')
    @patch('consumers.get_or_raise_config')
    def test_initialize_components(self, mock_get_config, mock_basic_config):
        """Test individual components of initialization."""
        mock_config_handler = Mock()
        mock_get_config.return_value = mock_config_handler
        
        # Test just the config setup part
        with patch.object(self.app_initializer, '_setup_llm_connection') as mock_setup_llm, \
             patch.object(self.app_initializer, '_setup_vector_db') as mock_setup_vector, \
             patch.object(self.app_initializer, '_initialize_assistants') as mock_init_assistants, \
             patch.object(self.app_initializer, '_load_cached_properties') as mock_load_cached:
            
            self.app_initializer.initialize()
            
            mock_basic_config.assert_called_once_with(level=logging.INFO)
            mock_get_config.assert_called_once()
            self.assertEqual(self.app_initializer.config_handler, mock_config_handler)
    
    @patch('consumers.setup_llmhub_connection')
    def test_setup_llm_connection_llmhub(self, mock_setup_llmhub):
        """Test LLM connection setup for LLMHUB."""
        mock_config_handler = Mock()
        mock_config_handler.get_config.return_value = {"service": "LLMHUB"}
        self.app_initializer.config_handler = mock_config_handler
        
        with patch('consumers.LLMHUB', "LLMHUB"), \
             patch('consumers.SAMY_EMP', "SAMY_EMP"):
            self.app_initializer._setup_llm_connection()
            mock_setup_llmhub.assert_called_once_with(project_name="SAMY_EMP")
    
    @patch('consumers.drop_and_resetup_vector_db')
    def test_setup_vector_db_localhost(self, mock_drop_resetup):
        """Test vector database setup for localhost."""
        mock_config_handler = Mock()
        vector_config = {"db_host": "localhost:5432"}
        mock_config_handler.get_config.return_value = vector_config
        self.app_initializer.config_handler = mock_config_handler
        
        self.app_initializer._setup_vector_db()
        
        mock_drop_resetup.assert_called_once_with(vector_config)
    
    @patch('consumers.get_guarded_yara_samy_assistant')
    def test_initialize_assistants(self, mock_get_assistant):
        """Test assistants initialization."""
        mock_config_handler = Mock()
        mock_config_handler.get_config.return_value = ["en", "fr"]
        self.app_initializer.config_handler = mock_config_handler
        
        mock_assistant_en = Mock()
        mock_assistant_fr = Mock()
        mock_get_assistant.side_effect = [mock_assistant_en, mock_assistant_fr]
        
        self.app_initializer._initialize_assistants()
        
        self.assertEqual(len(self.app_initializer.assistants), 2)
        self.assertEqual(self.app_initializer.assistants["en"], mock_assistant_en)
        self.assertEqual(self.app_initializer.assistants["fr"], mock_assistant_fr)


class TestHelloWorld(TestCase):
    """Test cases for HelloWorld consumer."""
    
    async def test_handle_request(self):
        """Test HelloWorld handle method."""
        consumer = HelloWorld()
        consumer.send_response = AsyncMock()
        
        await consumer.handle(b"")
        
        consumer.send_response.assert_called_once_with(
            200,
            b"Hello World",
            headers=[(b"Content-Type", b"text/plain")]
        )


class TestRagAnswerConsumer(TestCase):
    """Test cases for RagAnswerConsumer."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create consumer instance
        self.consumer = RagAnswerConsumer()
        self.consumer.scope = {"headers": [(b"language", b"en"), (b"x-bot-mode", b"default")]}
        
        # Mock the global app_initializer
        self.mock_assistant = Mock()
        self.consumer.response_handler = AsyncMock()
        self.consumer.validator = Mock()
    
    async def test_handle_success(self):
        """Test successful request handling."""
        # Mock validation responses
        self.consumer.validator.validate_request_data.return_value = (
            True, {"messages": [{"role": "user", "content": "test"}]}, None
        )
        self.consumer.validator.extract_and_validate_headers.return_value = (
            True, {"language": "en", "x_bot_mode": "default"}, None
        )
        
        with patch.object(self.consumer, '_process_rag_request') as mock_process:
            await self.consumer.handle(b'{"messages": []}')
            
            mock_process.assert_called_once()
    
    async def test_handle_invalid_request_data(self):
        """Test handling invalid request data."""
        self.consumer.validator.validate_request_data.return_value = (
            False, None, "Invalid data"
        )
        
        await self.consumer.handle(b'invalid json')
        
        self.consumer.response_handler.send_error_response.assert_called_once_with(
            400, "Invalid data"
        )
    
    @patch('consumers.logging.error')
    async def test_handle_unexpected_exception(self, mock_log_error):
        """Test handling unexpected exceptions."""
        self.consumer.validator.validate_request_data.side_effect = Exception("Unexpected error")
        
        await self.consumer.handle(b'{"messages": []}')
        
        mock_log_error.assert_called_once()
        self.consumer.response_handler.send_error_response.assert_called_once_with(
            500, json.dumps({"error": "Internal server error"})
        )
    
    @patch('consumers.Conversation')
    @patch('consumers.convert_to_RT_format')
    @patch('consumers.MessageRole')
    async def test_process_rag_request(self, mock_message_role, mock_convert, mock_conversation_class):
        """Test RAG request processing."""
        # Setup mocks
        mock_message_role.SYSTEM = "system"
        
        mock_conversation = Mock()
        mock_conversation.messages = [Mock(content="test query")]
        mock_conversation_class.return_value = mock_conversation
        
        mock_convert.return_value = {"role": "user", "content": "test"}
        
        # Mock the app_initializer assistants
        with patch('consumers.app_initializer') as mock_app_init:
            mock_app_init.assistants = {"en": self.mock_assistant}
            
            validated_data = {
                "messages": [{"role": "user", "content": "test query"}]
            }
            headers_data = {
                "language": "en",
                "x_bot_mode": "default"
            }
            
            await self.consumer._process_rag_request(validated_data, headers_data)
            
            # Verify streaming headers were sent
            self.consumer.response_handler.send_streaming_headers.assert_called_once()
            
            # Verify response was streamed
            self.consumer.response_handler.stream_assistant_response.assert_called_once_with(
                self.mock_assistant, mock_conversation, "default", "test query"
            )


# Alternative: Test configuration that completely isolates the global initialization
class TestWithIsolatedAppInitializer(TestCase):
    """Tests that completely avoid the global app_initializer."""
    
    def setUp(self):
        """Set up isolated test environment."""
        # Create a mock to replace the global app_initializer
        self.mock_app_initializer = Mock()
        self.mock_app_initializer.assistants = {"en": Mock(), "fr": Mock()}
    
    @patch('consumers.app_initializer')
    async def test_rag_consumer_with_mocked_global(self, mock_global_app_init):
        """Test RagAnswerConsumer with completely mocked global app_initializer."""
        mock_global_app_init.assistants = self.mock_app_initializer.assistants
        
        consumer = RagAnswerConsumer()
        consumer.scope = {"headers": [(b"language", b"en"), (b"x-bot-mode", b"default")]}
        
        # Mock all methods
        consumer.response_handler = AsyncMock()
        consumer.validator = Mock()
        
        consumer.validator.validate_request_data.return_value = (
            True, {"messages": [{"role": "user", "content": "test"}]}, None
        )
        consumer.validator.extract_and_validate_headers.return_value = (
            True, {"language": "en", "x_bot_mode": "default"}, None
        )
        
        with patch('consumers.Conversation'), \
             patch('consumers.convert_to_RT_format'), \
             patch('consumers.MessageRole'):
            
            await consumer.handle(b'{"messages": [{"role": "user", "content": "test"}]}')
            
            # Verify the flow completed
            consumer.response_handler.send_streaming_headers.assert_called_once()
            consumer.response_handler.stream_assistant_response.assert_called_once()


# Pytest configuration for better async support
@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    import asyncio
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


if __name__ == '__main__':
    # Clean up patches when running directly
    import atexit
    atexit.register(patch.stopall)
    pytest.main([__file__, "-v"])
