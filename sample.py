# assistant.py

import logging
from functools import cached_property
# Make sure to add this import
from typing import AsyncIterator

# Assuming these are defined in your project
from fortis.conversation.assistant import (
    Assistant,
    AssistantResponse,
    EnhancedAssistantResponse,
    StreamingAssistantResponse,
    FortisConversationalAssistant,
)
from fortis.conversation.message import Conversation, UserMessage, MessageRole
from fortis.llm import LanguageModel
from yara_samy.confidence_score import ConfidenceScore, build_confidence_score
from yara_samy.config import SAMY_EMP, ConfigHandler, get_or_raise_config
from yara_samy.models import AVAILABLE_LANGUAGES_TYPE
from yara_samy.utils import (
    get_conversational_assistant,
    is_at_doc,
    is_nota,
    load_nota_url_from_cos,
    pretty_at_doc,
    pretty_nota_search,
    strip_at_doc,
)
from yara_samy.guardrails import ClassificationGuardrail, UnusualPromptGuardrail
from yara_samy.utils_llm import get_language_model_from_service

from .utils import GuardedAssistant

# I'm assuming the streaming response from the underlying assistant looks something like this.
# You may need to adjust based on its actual implementation.
class StreamingEnhancedAssistantResponse(StreamingAssistantResponse):
    """Assumed structure for the underlying streaming response."""
    prompt: str | None
    keyword_search: bool | None
    references: list | None # Replace with your actual Reference type
    content_stream: AsyncIterator[str]

    class Config:
        arbitrary_types_allowed = True


class SamyOutput(EnhancedAssistantResponse):
    """Output of Yara Samy with confidence score."""
    confidence_score: ConfidenceScore | None


async def _stream_single_response(response: SamyOutput) -> AsyncIterator[dict]:
    """Wraps a single SamyOutput in an async generator to mimic a stream."""
    yield {"type": "full_response", "data": response.model_dump()}


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
        """Decides if the question matches a nota or not and answers it accordingly. (Non-streaming)"""
        query = conversation.messages[-1]
        assert isinstance(query, UserMessage)
        assert user_id, "user_id is not given."

        if not query.content.strip():
            return SamyOutput(
                prompt=None,
                keyword_search=None,
                references=None,
                content=self.config_handler.get_config("empty_input_message")[self.language],
                confidence_score=None,
            )

        if is_nota(query.content.strip()):
            return SamyOutput(
                prompt=None,
                keyword_search=None,
                references=None,
                content=pretty_nota_search(nota=query.content.strip(), nota_url_mapping=self.nota_url_mapping),
                confidence_score=None,
            )

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

        return await self.generate_llm_answer(conversation=conversation, user_id=user_id)

    async def next_message_stream(self, conversation: Conversation, user_id: str) -> AsyncIterator[dict]:
        """
        Decides if the question matches a nota or not and streams the answer.
        Yields a series of dictionaries representing stream events.
        """
        query = conversation.messages[-1]
        assert isinstance(query, UserMessage)
        assert user_id, "user_id is not given."

        if not query.content.strip():
            response = SamyOutput(
                prompt=None, keyword_search=None, references=None,
                content=self.config_handler.get_config("empty_input_message")[self.language],
                confidence_score=None
            )
            return _stream_single_response(response)

        if is_nota(query.content.strip()):
            response = SamyOutput(
                prompt=None, keyword_search=None, references=None,
                content=pretty_nota_search(nota=query.content.strip(), nota_url_mapping=self.nota_url_mapping),
                confidence_score=None
            )
            return _stream_single_response(response)

        if is_at_doc(query.content):
            content = strip_at_doc(message=query.content)
            if not content.strip():
                response = SamyOutput(
                    prompt=None, keyword_search=None, references=None,
                    content=self.config_handler.get_config("empty_doc_input_message")[self.language],
                    confidence_score=None
                )
                return _stream_single_response(response)

            conversation.messages[-1] = UserMessage(content=content, id=conversation.messages[-1].id)
            _, retrieval_result = await self.conversational_assistant.retrieval_result(
                conversation_window=self.conversational_assistant.get_conversation_window(conversation=conversation)
            )
            response = SamyOutput(
                prompt=None, keyword_search=None, references=None,
                content=pretty_at_doc([
                    qr.chunk.metadata.get("urls", ["No URL found for this document."]) for qr in retrieval_result
                ]),
                confidence_score=None
            )
            return _stream_single_response(response)

        return self.generate_llm_answer_stream(conversation=conversation, user_id=user_id)

    async def generate_llm_answer(self, conversation: Conversation, user_id: str) -> SamyOutput:
        """Get the final chat response and references. (Non-streaming)"""
        enhanced_assistant_response = await self.conversational_assistant.next_message(
            conversation=conversation, user_id=user_id
        )
        retriever_config = self.config_handler.get_config("retriever")

        if enhanced_assistant_response.keyword_search:
            enhanced_assistant_response.content = "\n".join(
                [retriever_config["keyword_detected"][self.language], enhanced_assistant_response.content]
            )
            confidence_score = None
        else:
            enhanced_assistant_response.content = "\n".join(
                [enhanced_assistant_response.content, retriever_config["further_detail_message"][self.language]]
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

    async def generate_llm_answer_stream(self, conversation: Conversation, user_id: str) -> AsyncIterator[dict]:
        """Streams the final chat response and metadata."""
        streaming_response: StreamingEnhancedAssistantResponse = await self.conversational_assistant.next_message_stream(
            conversation=conversation, user_id=user_id
        )
        retriever_config = self.config_handler.get_config("retriever")
        full_content_accumulator = []

        yield {
            "type": "metadata",
            "data": {
                "prompt": streaming_response.prompt,
                "keyword_search": streaming_response.keyword_search,
                "references": [ref.dict() for ref in streaming_response.references] if streaming_response.references else None,
            },
        }

        if streaming_response.keyword_search:
            initial_message = retriever_config["keyword_detected"][self.language] + "\n"
            yield {"type": "content_delta", "data": initial_message}
            full_content_accumulator.append(initial_message)

        async for chunk in streaming_response.content_stream:
            yield {"type": "content_delta", "data": chunk}
            full_content_accumulator.append(chunk)

        if not streaming_response.keyword_search:
            final_message = "\n" + retriever_config["further_detail_message"][self.language]
            yield {"type": "content_delta", "data": final_message}
            full_content_accumulator.append(final_message)

        final_answer = "".join(full_content_accumulator)
        confidence_score = None
        if not streaming_response.keyword_search:
            confidence_score = await build_confidence_score(
                question=conversation.messages[-1].content,
                references=streaming_response.references,
                answer=final_answer,
                config_handler=self.config_handler,
                language=self.language,
                llm=self.llm_confidence_score,
            )

        yield {
            "type": "confidence_score",
            "data": confidence_score.dict() if confidence_score else None,
        }

def get_guarded_yara_samy_assistant(language: AVAILABLE_LANGUAGES_TYPE) -> GuardedAssistant:
    """Returns an Assistant with the default Yara.Samy config given a language."""
    return GuardedAssistant(
        underlying_assistant=YaraSamyAssistant(config_handler=get_or_raise_config(SAMY_EMP), language=language),
        input_guard=UnusualPromptGuardrail().validate,
        output_guard=ClassificationGuardrail().validate,
			)
