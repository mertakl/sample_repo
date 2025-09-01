# In YaraSamyAssistant class in asistant.py

from typing import AsyncGenerator

# ... (other methods)

    async def generate_llm_answer(self, conversation: Conversation, user_id: str) -> SamyOutput:
        # ... (This method can remain as is for non-streaming calls if needed)
        pass

    async def stream_llm_answer(self, conversation: Conversation, user_id: str) -> AsyncGenerator[dict, None]:
        """
        Generates a stream of response packets: first the main answer, then the metadata.
        """
        # 1. Get the base response (the fast part)
        enhanced_assistant_response = await self.conversational_assistant.next_message(
            conversation=conversation, user_id=user_id
        )
        retriever_config = self.config_handler.get_config("retriever")

        # 2. Prepare and YIELD the first packet (the main response)
        if enhanced_assistant_response.keyword_search:
            content = "\n".join(
                [
                    retriever_config["keyword_detected"][self.language],
                    enhanced_assistant_response.content,
                ]
            )
        else:
            content = "\n".join(
                [
                    enhanced_assistant_response.content,
                    retriever_config["further_detail_message"][self.language],
                ]
            )
        
        # Update the content in the response object for later use
        enhanced_assistant_response.content = content

        # Create and yield the first packet
        response_packet = {
            "response": Message(role=MessageRole.ASSISTANT, content=content).model_dump()
        }
        yield response_packet

        # 3. Calculate the confidence score (the slow part)
        confidence_score = None
        if not enhanced_assistant_response.keyword_search:
            confidence_score = await build_confidence_score(
                question=conversation.messages[-1].content,
                references=enhanced_assistant_response.references,
                answer=enhanced_assistant_response.content,
                config_handler=self.config_handler,
                language=self.language,
                llm=self.llm_confidence_score,
            )

        # 4. Prepare and YIELD the second packet (the metadata)
        metadata = Metadata(
            confidence_score=confidence_score,
            prompt=enhanced_assistant_response.prompt,
            keyword_search=enhanced_assistant_response.keyword_search,
            references=enhanced_assistant_response.references,
        )
        
        metadata_packet = {"metadata": metadata.model_dump()}
        yield metadata_packet



# In your consumers.py file

# ... (imports)
import json

class RagAnswerConsumer(AsyncHttpConsumer):
    # ... (docstrings)

    async def handle(self, body):
        try:
            # ... (rest of your initial code: parsing request, getting language, etc.)

            #### SELECT APPROPRIATE ASSISTANT
            assistant = assistants[language]
            messages = [convert_to_RT_format(msg) for msg in request_messages if msg.get("role") != MessageRole.SYSTEM]
            conversation = Conversation(messages=messages)
            user_query = conversation.messages[-1].content

            #### PREPARE HEADERS FOR STREAMING
            await self.send_headers(
                headers=[
                    (b"Content-Type", b"application/x-ndjson"), # Use NDJSON for streaming JSON
                    (b"Cache-Control", b"no-cache"),
                    (b"Connection", b"keep-alive"),
                ]
            )

            # NOTE: We assume the main logic path will lead to a streaming LLM answer.
            # You might need to add logic to handle the other cases (is_nota, is_at_doc, etc.)
            # by having them return a compatible format or handling them before this loop.

            #### GET THE STREAMING RESPONSE
            if x_bot_mode == XBotMode.no_guardrails or should_avoid_guardrails(user_query=user_query):
                # For simplicity, this example assumes we use the underlying assistant directly.
                # You might need to adapt your GuardedAssistant to expose the streaming method.
                stream_generator = assistant.underlying_assistant.stream_llm_answer(conversation, user_id="user_id")
            elif x_bot_mode == XBotMode.default:
                # Assuming you've exposed `stream_llm_answer` through GuardedAssistant
                stream_generator = assistant.stream_llm_answer(conversation, user_id="user_id")
            else:
                raise ValueError(f"X Bot Mode {x_bot_mode} is not valid.")


            # Iterate through the async generator and send each packet
            async for packet in stream_generator:
                response_chunk = json.dumps(packet).encode("utf-8") + b"\n" # NDJSON ends with a newline
                await self.send_body(response_chunk, more_body=True)
            
            # Close the connection
            await self.send_body(b"", more_body=False)

        except Exception as e:
            error_msg = json.dumps({"error": str(e)})
            await self.send_response(500, error_msg.encode("utf-8"), headers=[(b"Content-Type", b"application/json")])
