# --- Shared constants (from previous refactor) ---

BASE_HEADERS = {
    "Language": "fr",
    "saml-groups": "[]",
    "X-Bot-Mode": "DEFAULT",
}

STREAMING_PAYLOAD = {
    "messages": [{"role": "user", "content": "Quel est le coût du pack Easy Go ?"}],
    "stream": True,
}

EXPECTED_EVENT_SEQUENCE = [
    "message.created",
    "message.in_progress",
    "message.content.started",
    "message.text.delta",
    "message.text.delta",
    "message.text.delta",
    "message.text.done",
    "message.content.done",
    "message.completed",
]


# --- Helpers ---

def parse_sse_packets(raw_packets: list[str]) -> list[dict]:
    """Parse raw SSE strings into a list of {event, data} dicts."""
    parsed = []
    for packet in raw_packets:
        event_type = data = None
        for line in packet.split("\n"):
            if line.startswith("event:"):
                event_type = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data = line.removeprefix("data:").strip()
        parsed.append({"event": event_type, "data": data})
    return parsed


# --- Tests ---

@pytest.mark.asyncio
async def test_end_to_end_text_streaming(api_client):
    async def async_message_stream():
        for chunk in ("Hello", "", "world!"):
            yield chunk

    mock_response = MagicMock()
    mock_response.content_stream = async_message_stream()
    mock_response.user_query = STREAMING_PAYLOAD["messages"][0]["content"]

    assistant = MagicMock()
    assistant.next_message_stream = AsyncMock(return_value=mock_response)

    with patch.object(app_initializer, "assistants", {"fr": assistant}):
        response = await build_post(api_client, STREAMING_PAYLOAD)

    assert response.status_code == 200

    raw_packets = []
    async for chunk in response.streaming_content:
        decoded = chunk.decode()
        assert isinstance(decoded, str)
        raw_packets.append(decoded)

    assert len(raw_packets) > 0

    parsed_packets = parse_sse_packets(raw_packets)

    assert len(parsed_packets) == len(EXPECTED_EVENT_SEQUENCE)
    for packet, expected_event in zip(parsed_packets, EXPECTED_EVENT_SEQUENCE):
        assert packet["event"] == expected_event
        assert isinstance(packet["data"], str)
