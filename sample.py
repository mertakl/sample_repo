async def get_eureka_response(self) -> AsyncGenerator[StreamEvent]:
    ...rest of the code
    direction = "input"
    try:
        _, eureka_response = await asyncio.gather(*tasks)
        direction = "output"
        accumulated = ""
        async for chunk in eureka_response.content_stream:
            accumulated += chunk
            yield event_sender.text_delta(delta=chunk)

        if any(is_numerical_cases(case) for case in [eureka_response.user_query, accumulated]):
            metrics.log(
                "numerical_case",
                user_query=eureka_response.user_query,
                answer=accumulated,
            )

        yield event_sender.text_done(accumulated)

        # ↓ Inner try: only guards the validate call
        try:
            await self._output_guard.validate(accumulated)
        except GuardrailTriggered as error:
            guardrail_reason = error.guardrail_result.reason
            yield event_sender.guardrail_triggered(
                name=error.guardrail_result.guardrail_name,
                reason=guardrail_reason,
            )
            accumulated += guardrail_reason

        # Runs after success OR guardrail — never after a generic exception
        yield event_sender.content_done(text=accumulated)
        yield event_sender.completed(content=accumulated)

    except Exception as error:  # pylint: disable=W0718
        logger.exception(error)
        yield event_sender.error(str(error))
