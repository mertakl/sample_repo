import json
import pytest


BASE_HEADERS = {
    "Language": "fr",
    "saml-groups": "[]",
    "X-Bot-Mode": "DEFAULT",
}


@pytest.fixture
def api_client():
    return AsyncClient()


def build_post(api_client, payload: dict):
    return api_client.post(
        reverse("create-message"),
        data=json.dumps(payload),
        content_type="application/json",
        headers=BASE_HEADERS,
    )


@pytest.mark.asyncio
async def test_successful_streaming_response(api_client):
    payload = {
        "messages": [{"role": "user", "content": "Quel est le coût du pack Easy Go ?"}],
        "stream": True,
    }
    response = await build_post(api_client, payload)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_bad_request(api_client):
    payload = {"test": "error", "stream": True}
    response = await build_post(api_client, payload)
    assert response.status_code == 400
