
async def next_message_stream(
    self, conversation: Conversation, user_id: str, conversation_id=str
) -> EnhancedStreamingAssistantResponse:
    """Generate the next message in streaming fashion. Takes into account the conversation history.
    
    Args:
        conversation (Conversation): Past conversation (including question) to be taken into account.
            Should include both User and Assistant messages.
        user_id: placeholder for SSO information
        conversation_id: conversation's id
    """
    assert user_id, "user_id is not given."
    prompt, retrieval_result, keyword_search = await self.prompt_and_refs(conversation=conversation)
    references = [document.chunk for document in retrieval_result]
    
    llm_start_time = time.time()
    
    for attempt in range(MAX_RETRY_LIM_COMPLETION + 1):
        try:
            answer_stream = self.llm.generate_answer_stream(
                prompt=prompt,
                generation_config=get_generation_config(
                    service=LIMAS, temperature=self.temperature, model_name=self.model_name, prompt=prompt
                ),
            )
            
            # Wrap the stream to log metrics after completion
            async def wrapped_stream():
                try:
                    async for chunk in answer_stream:
                        yield chunk
                finally:
                    # Log metrics after stream completes
                    duration_ms = (time.time() - llm_start_time) * 1000
                    self.metrics.log_llm_response_time(duration_ms, conversation_id)
                    self._log_metric("llm_response_time", {"duration_ms": duration_ms, "conversation_id": conversation_id})
            
            return EnhancedStreamingAssistantResponse(
                content_stream=wrapped_stream(), 
                references=references, 
                prompt=prompt, 
                keyword_search=keyword_search
            )
            
        except openai.RateLimitError as e:
            if attempt < MAX_RETRY_LIM_COMPLETION:
                time.sleep(1)
            else:
                raise LLMRateLimitError("Rate limit reach for LIM service.") from e
        except openai.APIError as e:
            raise LLMRequestError("Failed to call OpenAI complete API.") from e
        except Exception as e:
            raise LLMServiceException(
                "Something went wrong when generating answer with conversational assistant."
            ) from e

def _log_metric(self, event_type: str, data: dict[str, Any] | None = None):
    """Base method to log structured metrics."""
    self.logger.info(event_type, extra=data)
