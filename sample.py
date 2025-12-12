logger = logging.getLogger(__name__)

ASSISTANT_NAME = "LLM"
ACTION_CHAT_START = "chat.start"
ACTION_CHAT_MESSAGE = "chat.message"


class ChatStreamingService:
    """Real-time streaming chat with LLM. Orchestrates context reconstruction, LLM calls, streaming, storage."""

    def __init__(
        self,
        discussion_service: DiscussionService | None = None,
        llm_service: LLMService | None = None,
    ) -> None:
        """Initialize with discussion and LLM services (defaults to new instances)."""
        self._discussion_service = discussion_service or DiscussionService()
        self._llm_service = llm_service or LLMService()
        logger.debug("Initialized ChatStreamingService")

    async def stream_chat_message(
        self,
        command: StreamChatMessageCommand,
    ) -> AsyncIterator[StreamMessage]:
        """
        Process user message and stream LLM response in markdown format.

        ARCHITECTURE:
        - Backend knows it's "LLM", command.action: "chat.start" creates Discussion, "chat.message" validates
        - command.discussion_id: ALWAYS from Facade

        FLOW: Handle discussion → Save user msg → Reconstruct context → LLM call → Stream deltas → Save response
        PROTOCOL: Yields nested {action, payload} messages (WebSocket + SSE)
        CONTENT: LLM generates markdown with **bold**, *italic*, ```code``` syntax (no HTML tags).
        PERFORMANCE: Uses model_construct() for trusted data (~5µs vs ~30µs)
        """
        logger.info(
            "Starting chat stream - discussion_id: %s, action: %s, initiator: %s",
            command.discussion_id,
            command.action,
            command.initiator_id,
        )

        stream_context = StreamContext(command.discussion_id)

        try:
            await self._handle_discussion(command)
            await self._save_user_message(command)
            
            stream_context.message_id = str(uuid4())
            yield self._create_start_message(stream_context)

            context = await self._reconstruct_discussion_context(command.discussion_id)
            
            async for message in self._stream_llm_response(context, stream_context):
                yield message

            await self._save_assistant_message(command.discussion_id, stream_context)
            yield self._create_end_message(stream_context)

            logger.info(
                "Chat stream completed - discussion_id: %s, deltas: %d",
                command.discussion_id,
                stream_context.delta_count,
            )

        except ValueError as e:
            yield self._create_error_message(stream_context, e, is_validation_error=True)
        except Exception as e:
            logger.exception(
                "Chat stream failed - discussion_id: %s, error: %s",
                command.discussion_id,
                str(e),
            )
            yield self._create_error_message(stream_context, e, is_validation_error=False)

    async def _handle_discussion(self, command: StreamChatMessageCommand) -> None:
        """Handle discussion creation or validation based on action type."""
        if command.action == ACTION_CHAT_START:
            await self._create_discussion(command)
        else:
            await self._validate_discussion_exists(command.discussion_id)

    async def _create_discussion(self, command: StreamChatMessageCommand) -> None:
        """Create a new discussion."""
        logger.debug("Creating new discussion - discussion_id: %s", command.discussion_id)
        
        await self._discussion_service.create_discussion(
            CreateDiscussionCommand(
                initiator_id=command.initiator_id,
                business_context_id=command.business_context_id,
                discussion_id=command.discussion_id,
            )
        )
        
        logger.info("Discussion created - discussion_id: %s", command.discussion_id)

    async def _validate_discussion_exists(self, discussion_id: UUID) -> None:
        """Validate that a discussion exists."""
        logger.debug("Validating discussion exists - discussion_id: %s", discussion_id)
        
        discussion_obj = await sync_to_async(
            Discussion.objects.filter(discussion_id=discussion_id).first
        )()

        if discussion_obj is None:
            error_msg = f"Discussion not found: {discussion_id}"
            logger.error(error_msg)
            raise ValueError(error_msg)

    async def _save_user_message(self, command: StreamChatMessageCommand) -> None:
        """Save user message to database."""
        logger.debug("Storing user message - discussion_id: %s", command.discussion_id)
        
        user_message = await self._discussion_service.add_message(
            AddMessageCommand(
                initiator_id=command.initiator_id,
                business_context_id=str(command.discussion_id),
                discussion_id=command.discussion_id,
                role="user",
                content=command.content,
            )
        )
        
        logger.info(
            "User message stored - message_id: %s, discussion_id: %s",
            user_message.message_id,
            command.discussion_id,
        )

    async def _reconstruct_discussion_context(self, discussion_id: UUID) -> list:
        """Reconstruct full discussion context for LLM."""
        logger.debug("Reconstructing discussion context - discussion_id: %s", discussion_id)
        
        context = await sync_to_async(self._discussion_service.reconstruct_context)(
            discussion_id
        )
        
        logger.info(
            "Context reconstructed - discussion_id: %s, message_count: %d",
            discussion_id,
            len(context),
        )
        
        return context

    async def _stream_llm_response(
        self, 
        context: list, 
        stream_context: 'StreamContext'
    ) -> AsyncIterator[StreamContentMessage]:
        """Stream LLM response deltas with LaTeX conversion."""
        logger.debug("Calling LLM service - discussion_id: %s", stream_context.discussion_id)
        
        latex_converter = LatexStreamConverter()

        async for text_delta in self._llm_service.generate_streaming(context):
            stream_context.accumulated_response += text_delta
            stream_context.delta_count += 1

            converted_delta = latex_converter.process(text_delta)
            if converted_delta:
                yield self._create_content_message(stream_context.message_id, converted_delta)

        # Flush remaining buffered content
        final_chunk = latex_converter.flush()
        if final_chunk:
            yield self._create_content_message(stream_context.message_id, final_chunk)

        logger.info(
            "LLM streaming complete - discussion_id: %s, deltas: %d, response_length: %d",
            stream_context.discussion_id,
            stream_context.delta_count,
            len(stream_context.accumulated_response),
        )

    async def _save_assistant_message(
        self, 
        discussion_id: UUID, 
        stream_context: 'StreamContext'
    ) -> None:
        """Save complete assistant response to database."""
        canonical_content = convert_latex_to_dollar_signs(stream_context.accumulated_response)
        
        logger.debug("Storing assistant message - discussion_id: %s", discussion_id)
        
        assistant_message = await self._discussion_service.add_message(
            AddMessageCommand(
                initiator_id=ASSISTANT_NAME,
                business_context_id=str(discussion_id),
                discussion_id=discussion_id,
                role="assistant",
                content=canonical_content,
            )
        )
        
        logger.info(
            "Assistant message stored - message_id: %s, discussion_id: %s",
            assistant_message.message_id,
            discussion_id,
        )

    def _create_start_message(self, stream_context: 'StreamContext') -> StreamStartMessage:
        """Create stream start message."""
        return StreamStartMessage.model_construct(
            action="stream.start",
            payload=StreamStartPayload.model_construct(
                message_id=stream_context.message_id,
                discussion_id=str(stream_context.discussion_id),
                assistant_name=ASSISTANT_NAME,
            ),
        )

    def _create_content_message(self, message_id: str, content: str) -> StreamContentMessage:
        """Create stream content message."""
        return StreamContentMessage.model_construct(
            action="stream.content",
            payload=StreamContentPayload.model_construct(
                message_id=message_id,
                content=[
                    ContentBlock.model_construct(
                        type="markdown", 
                        payload=content, 
                        metadata=None
                    )
                ],
            ),
        )

    def _create_end_message(self, stream_context: 'StreamContext') -> StreamEndMessage:
        """Create stream end message."""
        return StreamEndMessage.model_construct(
            action="stream.end",
            payload=StreamEndPayload.model_construct(
                message_id=stream_context.message_id,
                sources=None,
                metadata={"total_deltas": stream_context.delta_count},
            ),
        )

    def _create_error_message(
        self, 
        stream_context: 'StreamContext', 
        error: Exception,
        is_validation_error: bool
    ) -> StreamErrorMessage:
        """Create stream error message."""
        error_message_id = stream_context.message_id or str(uuid4())
        
        if is_validation_error:
            error_msg_lower = str(error).lower()
            error_code = (
                "discussion_not_found" 
                if "discussion not found" in error_msg_lower 
                else "validation_error"
            )
            logger.warning(
                "Chat stream validation failed - discussion_id: %s, error: %s",
                stream_context.discussion_id,
                str(error),
            )
        else:
            error_code = "llm_error"

        return StreamErrorMessage.model_construct(
            action="stream.error",
            payload=StreamErrorPayload.model_construct(
                message_id=error_message_id,
                discussion_id=str(stream_context.discussion_id),
                request_message_id=None,
                error_code=error_code,
                error_text=str(error),
            ),
        )


class StreamContext:
    """Context object to track streaming state."""
    
    def __init__(self, discussion_id: UUID):
        self.discussion_id = discussion_id
        self.message_id: str | None = None
        self.accumulated_response: str = ""
        self.delta_count: int = 0


--------------------------------------------------

logger = logging.getLogger(__name__)

# Type alias for chat message format
ChatMessage = dict[Literal["role", "content"], str]

# Constants
MAX_PAGE_SIZE_DISCUSSIONS = 100
MAX_PAGE_SIZE_MESSAGES = 200
DEFAULT_DISCUSSION_PAGE_SIZE = 20
DEFAULT_MESSAGE_PAGE_SIZE = 50


class DiscussionService:
    """
    Service for managing discussions and messages with LLM context reconstruction.

    Key responsibilities:
    - Create and manage Discussion containers
    - Add messages (user and assistant) to discussions
    - Reconstruct discussion history for LLM API calls
    - Enforce business rules (message limits, content validation)
    """

    async def create_discussion(self, command: CreateDiscussionCommand) -> Discussion:
        """
        Create new discussion container.

        ARCHITECTURE:
        - command.discussion_id is REQUIRED (provided by Facade)
        - Backend uses the provided discussion_id (no auto-generation)
        - Facade generates UUID and creates DiscussionPreview before calling Backend
        - Backend doesn't need assistant_name - it IS the LLM assistant

        Args:
            command: CreateDiscussionCommand with discussion_id, initiator_id

        Returns:
            Discussion: Created discussion instance

        Raises:
            Exception: If discussion creation fails
        """
        logger.info(
            "Creating discussion - initiator_id: %s, discussion_id: %s",
            command.initiator_id,
            command.discussion_id,
        )

        try:
            discussion = await sync_to_async(self._create_discussion_transaction)(command)

            logger.debug(
                "Discussion created - discussion_id: %s, user_id: %s",
                discussion.discussion_id,
                discussion.user_id,
            )

            return discussion

        except Exception as e:
            logger.exception("Discussion creation failed - error: %s", str(e))
            raise

    @staticmethod
    @transaction.atomic
    def _create_discussion_transaction(command: CreateDiscussionCommand) -> Discussion:
        """Create discussion within a transaction."""
        return Discussion.objects.create(
            discussion_id=command.discussion_id,
            user_id=command.initiator_id,
        )

    async def add_message(self, command: AddMessageCommand) -> Message:
        """
        Add message to discussion (user or assistant).

        Updates discussion metadata (message_count, updated_at, title).
        Title is extracted from first user message.

        Args:
            command: AddMessageCommand with discussion_id, role, content

        Returns:
            Message: Created message instance

        Raises:
            ValueError: If discussion doesn't exist
            DjangoValidationError: If validation fails
        """
        logger.info(
            "Adding message - discussion_id: %s, role: %s, initiator_id: %s",
            command.discussion_id,
            command.role,
            command.initiator_id,
        )

        try:
            message = await sync_to_async(self._add_message_transaction)(command)
            return message

        except (DjangoValidationError, ValueError):
            raise
        except Exception as e:
            logger.exception(
                "Message addition failed - discussion_id: %s, error: %s",
                command.discussion_id,
                str(e),
            )
            raise

    @staticmethod
    @transaction.atomic
    def _add_message_transaction(command: AddMessageCommand) -> Message:
        """Add message within a transaction."""
        # Verify discussion exists
        try:
            discussion = Discussion.objects.get(discussion_id=command.discussion_id)
        except Discussion.DoesNotExist as e:
            error_msg = f"Discussion {command.discussion_id} does not exist"
            logger.warning(error_msg)
            raise ValueError(error_msg) from e

        # Create and validate message
        message = Message(
            discussion=discussion,
            role=command.role,
            content=command.content,
        )
        message.full_clean()
        message.save()

        logger.debug(
            "Message created - message_id: %s, role: %s, content_length: %d",
            message.message_id,
            message.role,
            len(message.content),
        )

        # Update discussion metadata
        try:
            discussion.increment_message_count()
            discussion.refresh_from_db()
        except DjangoValidationError as e:
            logger.warning(
                "Message addition rejected - discussion_id: %s, reason: %s",
                command.discussion_id,
                str(e),
            )
            violated_rules = e.message_dict.get("violated_rules", [])
            raise DjangoValidationError({
                "message_addition": str(e),
                "violated_rules": violated_rules,
            }) from e

        return message

    def reconstruct_context(self, discussion_id: UUID) -> list[ChatMessage]:
        """
        Reconstruct full discussion context for LLM.

        This is the heart of the LLM assistant.
        Rebuilds the complete message history in chat completions format
        so the LLM has full context when generating responses.

        Process:
        1. Fetch all messages for discussion in chronological order
        2. Strip HTML tags (LLMs prefer plain text)
        3. Format as chat messages: [{"role": "user/assistant", "content": "..."}]

        Args:
            discussion_id: UUID of discussion to reconstruct

        Returns:
            list[ChatMessage]: Messages in chat completions format
            Example: [
                {"role": "user", "content": "What is Python?"},
                {"role": "assistant", "content": "Python is a programming language..."},
                {"role": "user", "content": "Tell me more"}
            ]

        Raises:
            Discussion.DoesNotExist: If discussion not found

        Note: System prompt is handled by LLMService, not included here.
        """
        logger.debug("Reconstructing context - discussion_id: %s", discussion_id)

        try:
            # Verify discussion exists
            discussion = Discussion.objects.get(discussion_id=discussion_id)

            # Fetch all messages in chronological order
            messages = Message.objects.filter(discussion=discussion).order_by("created_at")

            # Build context in chat completions format
            context = [
                {"role": msg.role, "content": strip_html_tags(msg.content)}
                for msg in messages
            ]

            logger.info(
                "Context reconstructed - discussion_id: %s, messages: %d",
                discussion_id,
                len(context),
            )

            return context

        except Discussion.DoesNotExist:
            error_msg = f"Discussion {discussion_id} does not exist"
            logger.error(error_msg)
            raise

    def get_discussion(self, discussion_id: UUID) -> Discussion | None:
        """
        Retrieve a single discussion by ID.

        Args:
            discussion_id: UUID of the discussion

        Returns:
            Discussion object if found, None otherwise
        """
        logger.debug("Getting discussion - discussion_id: %s", discussion_id)

        try:
            discussion = Discussion.objects.get(discussion_id=discussion_id)
            logger.debug("Found discussion - discussion_id: %s", discussion_id)
            return discussion
        except Discussion.DoesNotExist:
            logger.debug("Discussion not found - discussion_id: %s", discussion_id)
            return None

    def get_discussions(
        self, 
        page: int = 1, 
        page_size: int = DEFAULT_DISCUSSION_PAGE_SIZE
    ) -> list[Discussion]:
        """
        Retrieve list of discussions with pagination.

        Args:
            page: Page number (1-indexed)
            page_size: Number of discussions per page (max 100)

        Returns:
            List of Discussion objects, ordered by most recent first
        """
        page_size = min(page_size, MAX_PAGE_SIZE_DISCUSSIONS)
        offset = self._calculate_offset(page, page_size)

        logger.debug(
            "Getting discussions - page: %d, page_size: %d, offset: %d",
            page,
            page_size,
            offset,
        )

        discussions = list(
            Discussion.objects.all()
            .order_by("-updated_at")[offset : offset + page_size]
        )

        logger.debug("Retrieved %d discussions", len(discussions))
        return discussions

    def get_messages(
        self,
        discussion_id: UUID,
        page: int = 1,
        page_size: int = DEFAULT_MESSAGE_PAGE_SIZE,
    ) -> list[Message]:
        """
        Retrieve paginated messages for a specific discussion.

        Args:
            discussion_id: UUID of discussion
            page: Page number (1-indexed)
            page_size: Number of messages per page (max 200)

        Returns:
            List of Message objects in chronological order

        Raises:
            ValueError: If discussion doesn't exist
        """
        self._verify_discussion_exists(discussion_id)

        page_size = min(page_size, MAX_PAGE_SIZE_MESSAGES)
        offset = self._calculate_offset(page, page_size)

        logger.debug(
            "Getting messages - discussion_id: %s, page: %d, page_size: %d, offset: %d",
            discussion_id,
            page,
            page_size,
            offset,
        )

        messages = list(
            Message.objects.filter(discussion_id=discussion_id)
            .order_by("created_at")[offset : offset + page_size]
        )

        logger.debug("Retrieved %d messages", len(messages))
        return messages

    @staticmethod
    def _calculate_offset(page: int, page_size: int) -> int:
        """Calculate offset for pagination."""
        return (page - 1) * page_size

    @staticmethod
    def _verify_discussion_exists(discussion_id: UUID) -> None:
        """
        Verify that a discussion exists.

        Raises:
            ValueError: If discussion doesn't exist
        """
        if not Discussion.objects.filter(discussion_id=discussion_id).exists():
            error_msg = f"Discussion {discussion_id} does not exist"
            logger.warning(error_msg)
            raise ValueError(error_msg)


-----------------------


logger = logging.getLogger(__name__)


class Message(TypedDict):
    """Type definition for chat messages."""
    role: str
    content: str


@dataclass(frozen=True)
class LLMConfig:
    """Configuration for LLM service loaded from environment variables."""
    
    base_url: str
    model: str
    verify_ssl: bool
    temperature: float
    max_tokens: int
    api_key: str | None = None
    system_prompt: str | None = None
    
    @classmethod
    def from_environment(cls) -> "LLMConfig":
        """
        Load configuration from environment variables.
        
        Returns:
            LLMConfig: Validated configuration
            
        Raises:
            ValueError: If required environment variables are missing or invalid
        """
        # Required variables
        base_url = cls._get_required_env("LLM_BASE_URL")
        model = cls._get_required_env("LLM_MODEL")
        verify_ssl_str = cls._get_required_env("LLM_VERIFY_SSL")
        temp_str = cls._get_required_env("LLM_TEMPERATURE")
        max_tokens_str = cls._get_required_env("LLM_MAX_TOKENS")
        
        # Parse and validate
        verify_ssl = verify_ssl_str.lower() == "true"
        
        try:
            temperature = float(temp_str)
            if not 0.0 <= temperature <= 2.0:
                raise ValueError("LLM_TEMPERATURE must be between 0.0 and 2.0")
        except ValueError as e:
            raise ValueError(f"Invalid LLM_TEMPERATURE: {temp_str}") from e
        
        try:
            max_tokens = int(max_tokens_str)
            if max_tokens <= 0:
                raise ValueError("LLM_MAX_TOKENS must be positive")
        except ValueError as e:
            raise ValueError(f"Invalid LLM_MAX_TOKENS: {max_tokens_str}") from e
        
        # Optional variables
        api_key = os.getenv("LLM_API_KEY")
        if not api_key:
            logger.warning("No API key configured (OK if not required by endpoint)")
        
        system_prompt = os.getenv("LLM_SYSTEM_PROMPT") or cls._default_system_prompt()
        
        return cls(
            base_url=base_url,
            model=model,
            verify_ssl=verify_ssl,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=api_key,
            system_prompt=system_prompt,
        )
    
    @staticmethod
    def _get_required_env(var_name: str) -> str:
        """Get required environment variable or raise error."""
        value = os.getenv(var_name)
        if not value:
            raise ValueError(
                f"{var_name} environment variable not set. "
                "Please source config-llm.ps1: . .\\config-llm.ps1"
            )
        return value
    
    @staticmethod
    def _default_system_prompt() -> str:
        """Return default system prompt."""
        return (
            "You are a helpful assistant. Respond in markdown format. "
            "Use markdown syntax for formatting: "
            "**bold** for emphasis, *italic* for subtle emphasis, "
            "```language for code blocks, | tables | for tabular data, "
            "$..$ for inline math (e.g., $E = mc^2$), $$..$$ for block math (centered equations). "
            "ALWAYS use $ delimiters for math, NEVER use parentheses like (\\frac{1}{2}). "
            "Do NOT use HTML tags."
        )


class LLMService:
    """
    Generic client for OpenAI-compatible LLM APIs with streaming support.

    REQUIRED: Environment variables must be set before initialization.
    Use config-llm.ps1 to configure: . .\config-llm.ps1

    Required environment variables:
    - LLM_BASE_URL: API endpoint (no default)
    - LLM_MODEL: Model identifier (no default)
    - LLM_API_KEY: Authentication key (optional if not required by endpoint)
    - LLM_VERIFY_SSL: SSL verification "true"/"false" (no default)
    - LLM_TEMPERATURE: Sampling temperature 0.0-2.0 (no default)
    - LLM_MAX_TOKENS: Maximum response tokens (no default)

    Optional environment variables:
    - LLM_SYSTEM_PROMPT: Default system message

    Example usage:
        # PowerShell: . .\config-llm.ps1
        service = LLMService()
        messages = [
            {"role": "user", "content": "What is 2+2?"}
        ]
        async for text_delta in service.generate_streaming(messages):
            print(text_delta, end='')
    """

    def __init__(self, config: LLMConfig | None = None) -> None:
        """
        Initialize LLM service with configuration.

        Args:
            config: Optional LLMConfig. If None, loads from environment.

        Raises:
            ValueError: If required environment variables are not set
        """
        self.config = config or LLMConfig.from_environment()
        
        logger.info(
            "LLMService initialized - "
            "URL: %s, Model: %s, SSL Verify: %s, "
            "Temperature: %s, Max Tokens: %s, API Key: %s",
            self.config.base_url,
            self.config.model,
            self.config.verify_ssl,
            self.config.temperature,
            self.config.max_tokens,
            "configured" if self.config.api_key else "not set",
        )

    async def generate_streaming(
        self,
        messages: list[Message],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """
        Generate streaming response from LLM.

        Sends messages to LLM API and yields text deltas as they arrive.
        Prepends system prompt if configured and not already in messages.

        Args:
            messages: List of {"role": "user/assistant/system", "content": "..."}
                     Role must be one of: "system", "user", "assistant"
                     Messages should be in chronological order
            temperature: Sampling temperature (0.0-2.0), defaults to config
                        Lower = more deterministic, Higher = more creative
            max_tokens: Maximum tokens in response, defaults to config

        Yields:
            str: Text deltas as they arrive from the API

        Raises:
            RuntimeError: If API request fails

        Example:
            messages = [{"role": "user", "content": "What is Python?"}]
            async for delta in service.generate_streaming(messages):
                print(delta, end='', flush=True)
        """
        temp = temperature if temperature is not None else self.config.temperature
        max_tok = max_tokens if max_tokens is not None else self.config.max_tokens
        
        prepared_messages = self._prepare_messages(messages)
        
        async with self._create_client() as client:
            async for delta in self._stream_completion(client, prepared_messages, temp, max_tok):
                yield delta

    def _prepare_messages(self, messages: list[Message]) -> list[Message]:
        """Prepend system prompt if configured and not already present."""
        if self.config.system_prompt and (not messages or messages[0]["role"] != "system"):
            return [{"role": "system", "content": self.config.system_prompt}] + messages
        return messages

    def _create_client(self) -> httpx.AsyncClient:
        """Create HTTP client with configured settings."""
        return httpx.AsyncClient(verify=self.config.verify_ssl, timeout=60.0)

    def _build_headers(self) -> dict[str, str]:
        """Build request headers with optional authentication."""
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _build_payload(
        self,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
    ) -> dict:
        """Build request payload for API."""
        return {
            "model": self.config.model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

    async def _stream_completion(
        self,
        client: httpx.AsyncClient,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        """Stream completion from API."""
        headers = self._build_headers()
        payload = self._build_payload(messages, temperature, max_tokens)
        
        logger.debug("Sending request to %s/chat/completions", self.config.base_url)
        logger.debug("Payload: %s", json.dumps(payload, indent=2))
        
        try:
            async with client.stream(
                "POST",
                f"{self.config.base_url}/chat/completions",
                headers=headers,
                json=payload,
            ) as response:
                response.raise_for_status()
                
                async for delta in self._parse_sse_stream(response):
                    yield delta
                    
        except httpx.HTTPStatusError as e:
            raise RuntimeError(self._format_http_error(e)) from e
        except httpx.RequestError as e:
            error_msg = f"Failed to connect to LLM API at {self.config.base_url}: {e}"
            logger.error("LLM API request failed: %s", error_msg)
            raise RuntimeError(error_msg) from e
        except Exception as e:
            logger.error("LLM generation failed: %s", e, exc_info=True)
            raise

    async def _parse_sse_stream(self, response: httpx.Response) -> AsyncIterator[str]:
        """Parse Server-Sent Events stream."""
        async for line in response.aiter_lines():
            if not line.strip() or not line.startswith("data: "):
                continue
            
            data = line[6:]  # Remove "data: " prefix
            
            if data == "[DONE]":
                break
            
            try:
                chunk = json.loads(data)
                
                # Skip chunks with empty choices
                if not chunk.get("choices"):
                    continue
                
                delta = chunk["choices"][0]["delta"]
                if "content" in delta:
                    yield delta["content"]
                    
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                logger.warning("Failed to parse chunk: %s - Line: %s", e, line)
                continue

    def _format_http_error(self, error: httpx.HTTPStatusError) -> str:
        """Format HTTP error into user-friendly message."""
        status = error.response.status_code
        base_msg = f"LLM API returned HTTP {status}"
        
        error_messages = {
            401: " - Authentication failed. Please set LLM_API_KEY environment variable or configure GitHub CLI.",
            502: " - Bad Gateway. The LLM API server is unavailable or returned an error.",
            503: " - Service Unavailable. The LLM API is temporarily unavailable.",
        }
        
        if status in error_messages:
            message = base_msg + error_messages[status]
        elif status >= 500:
            message = base_msg + " - Server error. The LLM API encountered an internal error."
        else:
            message = base_msg
        
        logger.error("LLM API HTTP error: %s - URL: %s", message, self.config.base_url)
        return message
