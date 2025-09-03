import asyncio
import logging
from typing import AsyncGenerator, Callable, Awaitable, Literal, Annotated
from fastapi import FastAPI, Header
from fastapi.responses import StreamingResponse
import json

# GuardedAssistant with streaming implementation
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

    async def next_message_stream(self, conversation: Conversation, **kwargs) -> AsyncGenerator[YaraSamyResponse, None]:
        """Streaming version with guardrails applied."""
        assert len(conversation.messages) > 0
        last_message = conversation.messages[-1]
        assert isinstance(last_message, UserMessage), "The conversation should end with a UserMessage"
        
        # Apply input guard first
        if self.input_guard:
            try:
                await self.input_guard(last_message.string_content)
            except GuardrailError as error:
                logging.info(f"Guardrail triggered for input message {last_message}")
                yield YaraSamyResponse(
                    message=Message(role=MessageRole.ASSISTANT, content=error.message)
                )
                return
        
        # Stream from underlying assistant
        accumulated_content = ""
        final_response = None
        
        try:
            async for response in self.underlying_assistant.next_message_stream(conversation=conversation, **kwargs):
                # Accumulate content for output guard validation
                if response.message and response.message.content:
                    accumulated_content += response.message.content
                
                # Store the final response for metadata
                final_response = response
                
                # Yield the response (we'll validate after streaming completes)
                yield response
                
        except Exception as e:
            logging.error(f"Error in underlying assistant streaming: {str(e)}")
            yield YaraSamyResponse(
                message=Message(role=MessageRole.ASSISTANT, content="An error occurred while processing your request.")
            )
            return
        
        # Apply output guard on accumulated content
        if self.output_guard and accumulated_content:
            try:
                await self.output_guard(accumulated_content)
            except GuardrailError as error:
                logging.info(f"Guardrail triggered for output message")
                # Send a replacement message indicating guardrail trigger
                yield YaraSamyResponse(
                    message=Message(role=MessageRole.ASSISTANT, content=error.message),
                    metadata=Metadata(
                        confidence_score=None,
                        prompt=None,
                        keyword_search=None,
                        references=None,
                    ) if final_response and final_response.metadata else None
                )


# Updated FastAPI setup with streaming endpoint
logging.basicConfig(level=logging.INFO)
config_handler = get_or_raise_config(SAMY_EMP)

if config_handler.get_config("llm_model")["service"] == LLMHUB:
    setup_llmhub_connection(project_name=SAMY_EMP)

if "localhost" in config_handler.get_config("vector_db")["db_host"]:
    drop_and_resetup_vector_db(config_handler.get_config("vector_db"))

assistants: dict[AVAILABLE_LANGUAGES_TYPE, GuardedAssistant] = {
    lang: get_guarded_yara_samy_assistant(language=lang) 
    for lang in config_handler.get_config("languages")
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
        service=llm_config["service"], 
        model_name=model_name, 
        rpm=llm_config.get("rpm_limit")
    )
    prompt = Prompt(messages=[UserMessage(content="Hi")])
    generation_config = GenerationConfig(temperature=0, max_tokens=10)
    
    try:
        await llm.generate_answer(prompt=prompt, generation_config=generation_config)
    except Exception:  # pylint: disable=W0718
        return False
        
    for language, assistant in assistants.items():
        logging.info("Refreshing %s assistant", language)
        assistant.underlying_assistant.conversational_assistant.llm = llm
    return True


@app.post("/get_response")
async def get_response(
    request: YaraSamyRequest,
    language: Annotated[AVAILABLE_LANGUAGES_TYPE, Header()] = "fr",
    x_bot_mode: Literal[XBotMode.default, XBotMode.no_guardrails] = XBotMode.default,
) -> YaraSamyResponse:
    """Yara.Samy request route (non-streaming)."""
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


@app.post("/get_response_stream")
async def get_response_stream(
    request: YaraSamyRequest,
    language: Annotated[AVAILABLE_LANGUAGES_TYPE, Header()] = "fr",
    x_bot_mode: Literal[XBotMode.default, XBotMode.no_guardrails] = XBotMode.default,
):
    """Yara.Samy streaming request route."""
    logging.debug("Streaming Mode: %s", x_bot_mode)
    
    async def generate_stream():
        """Generator function for streaming response."""
        try:
            assistant = assistants[language]
            conversation = Conversation(
                messages=[msg.to_rag_toolbox() for msg in request.messages if msg.role != MessageRole.SYSTEM]
            )
            user_query = conversation.messages[-1].content
            
            # Choose the appropriate streaming method based on mode
            if x_bot_mode == XBotMode.no_guardrails or should_avoid_guardrails(user_query=user_query):
                stream_generator = assistant.underlying_assistant.next_message_stream(
                    conversation, user_id="user_id"
                )
            elif x_bot_mode == XBotMode.default:
                stream_generator = assistant.next_message_stream(
                    conversation, user_id="user_id"
                )
            else:
                raise ValueError(f"X Bot Mode {x_bot_mode} is not valid.")
            
            # Stream the responses
            async for yara_response in stream_generator:
                chunk = json.dumps(yara_response.model_dump()) + "\n"
                yield chunk.encode("utf-8")
                
        except Exception as e:
            logging.error(f"Error in streaming response: {str(e)}")
            error_response = YaraSamyResponse(
                message=Message(
                    role=MessageRole.ASSISTANT, 
                    content="An error occurred while processing your request."
                )
            )
            chunk = json.dumps(error_response.model_dump()) + "\n"
            yield chunk.encode("utf-8")
    
    return StreamingResponse(
        generate_stream(),
        media_type="application/json",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.post("/get_response_sse")
async def get_response_sse(
    request: YaraSamyRequest,
    language: Annotated[AVAILABLE_LANGUAGES_TYPE, Header()] = "fr",
    x_bot_mode: Literal[XBotMode.default, XBotMode.no_guardrails] = XBotMode.default,
):
    """Yara.Samy Server-Sent Events streaming route."""
    logging.debug("SSE Streaming Mode: %s", x_bot_mode)
    
    async def generate_sse_stream():
        """Generator function for SSE streaming response."""
        try:
            assistant = assistants[language]
            conversation = Conversation(
                messages=[msg.to_rag_toolbox() for msg in request.messages if msg.role != MessageRole.SYSTEM]
            )
            user_query = conversation.messages[-1].content
            
            # Choose the appropriate streaming method based on mode
            if x_bot_mode == XBotMode.no_guardrails or should_avoid_guardrails(user_query=user_query):
                stream_generator = assistant.underlying_assistant.next_message_stream(
                    conversation, user_id="user_id"
                )
            elif x_bot_mode == XBotMode.default:
                stream_generator = assistant.next_message_stream(
                    conversation, user_id="user_id"
                )
            else:
                raise ValueError(f"X Bot Mode {x_bot_mode} is not valid.")
            
            # Stream the responses in SSE format
            async for yara_response in stream_generator:
                data = json.dumps(yara_response.model_dump())
                yield f"data: {data}\n\n"
                
            # Send end marker
            yield "data: [DONE]\n\n"
                
        except Exception as e:
            logging.error(f"Error in SSE streaming response: {str(e)}")
            error_response = YaraSamyResponse(
                message=Message(
                    role=MessageRole.ASSISTANT, 
                    content="An error occurred while processing your request."
                )
            )
            data = json.dumps(error_response.model_dump())
            yield f"data: {data}\n\n"
            yield "data: [DONE]\n\n"
    
    return StreamingResponse(
        generate_sse_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
								 )
