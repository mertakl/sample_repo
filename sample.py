async def next_message_stream(self, conversation: Conversation, user_id: str) -> AsyncGenerator[dict, None]:
    """Generates a streaming response for all cases (nota, @doc, and LLM answers).
    
    Args:
        conversation: conversation history of user and assistant
        user_id: ID of the user for SSO filtering
        
    Yields:
        dict: Streaming packets containing response and/or metadata
    """
    query = conversation.messages[-1]
    assert isinstance(query, UserMessage)
    # For now, we don't use user_id. It's a placeholder for SSO information.
    assert user_id, "user_id is not given."
    
    if not query.content.strip():
        # The input is empty - yield single response
        content = self.config_handler.get_config("empty_input_message")[self.language]
        response_packet = {
            "response": Message(role=MessageRole.ASSISTANT, content=content).model_dump()
        }
        yield response_packet
        
        # Yield metadata packet
        metadata = Metadata(
            confidence_score=None,
            prompt=None,
            keyword_search=None,
            references=None,
        )
        metadata_packet = {"metadata": metadata.model_dump()}
        yield metadata_packet
        return

    # When a user asks a question with just a nota, we return the docs matching to that nota
    if is_nota(query.content.strip()):
        content = pretty_nota_search(nota=query.content.strip(), nota_url_mapping=self.nota_url_mapping)
        response_packet = {
            "response": Message(role=MessageRole.ASSISTANT, content=content).model_dump()
        }
        yield response_packet
        
        # Yield metadata packet
        metadata = Metadata(
            confidence_score=None,
            prompt=None,
            keyword_search=None,
            references=None,
        )
        metadata_packet = {"metadata": metadata.model_dump()}
        yield metadata_packet
        return

    # When a user uses the @doc functionality, we return links to document without final LLM call
    if is_at_doc(query.content):
        content = strip_at_doc(message=query.content)
        if not content.strip():
            content = self.config_handler.get_config("empty_doc_input_message")[self.language]
            response_packet = {
                "response": Message(role=MessageRole.ASSISTANT, content=content).model_dump()
            }
            yield response_packet
            
            # Yield metadata packet
            metadata = Metadata(
                confidence_score=None,
                prompt=None,
                keyword_search=None,
                references=None,
            )
            metadata_packet = {"metadata": metadata.model_dump()}
            yield metadata_packet
            return
            
        # Update the conversation with stripped content
        conversation.messages[-1] = UserMessage(content=content, id=conversation.messages[-1].id)
        _, retrieval_result = await self.conversational_assistant.retrieval_result(
            conversation_window=self.conversational_assistant.get_conversation_window(conversation=conversation)
        )
        
        content = pretty_at_doc(
            [
                query_response.chunk.metadata.get("urls", ["No URL found for this document."])
                for query_response in retrieval_result
            ]
        )
        
        response_packet = {
            "response": Message(role=MessageRole.ASSISTANT, content=content).model_dump()
        }
        yield response_packet
        
        # Yield metadata packet
        metadata = Metadata(
            confidence_score=None,
            prompt=None,
            keyword_search=None,
            references=None,
        )
        metadata_packet = {"metadata": metadata.model_dump()}
        yield metadata_packet
        return

    # Classic RAG question or keyword search that requires an LLM call to generate the answer
    async for packet in self.generate_llm_answer_stream(conversation=conversation, user_id=user_id):
        yield packet

async def generate_llm_answer_stream(self, conversation: Conversation, user_id: str) -> AsyncGenerator[dict, None]:
    """Get the final chat response and references in streaming format.

    Args:
        conversation: conversation history
        user_id: id of the user
        
    Yields:
        dict: Streaming packets containing response and metadata
    """
    enhanced_assistant_response = await self.conversational_assistant.next_message(
        conversation=conversation, user_id=user_id
    )
    retriever_config = self.config_handler.get_config("retriever")

    # Prepare the content based on keyword_search flag
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

    # Create and yield response packet
    response_packet = {
        "response": Message(role=MessageRole.ASSISTANT, content=content).model_dump()
    }
    yield response_packet

    # Calculate the confidence score (only for non-keyword searches)
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

    # Prepare and yield metadata packet
    metadata = Metadata(
        confidence_score=confidence_score,
        prompt=enhanced_assistant_response.prompt,
        keyword_search=enhanced_assistant_response.keyword_search,
        references=enhanced_assistant_response.references,
    )
    metadata_packet = {"metadata": metadata.model_dump()}
    yield metadata_packet
