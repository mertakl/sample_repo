class MessageRole(str, Enum):
    """LLM Message Role Type."""

    ASSISTANT = "assistant"
    SYSTEM = "system"
    USER = "user"


class Message(ConfiguredBaseModel):
    """Message schema."""

    role: MessageRole
    content: str

    def to_rag_toolbox(self) -> RTMessage:
        """Helper: convert to RAG-Toolbox object."""
        match self.role:
            case MessageRole.SYSTEM:
                return SystemMessage(content=self.content)
            case MessageRole.ASSISTANT:
                return AssistantMessage(content=self.content)
            case MessageRole.USER:
                return UserMessage(content=self.content)
            case _:
                raise NotImplementedError


class Metadata(ConfiguredBaseModel):
    """Metadata Schema for yara samy response."""

    confidence_score: ConfidenceScore | None
    prompt: Prompt | None
    keyword_search: bool
    references: list[DocumentChunk] | None | None

"Error in underlying assistant streaming: Cannot instantiate typing.Union"
