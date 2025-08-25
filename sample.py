##Can you also fix these unit tests?
from unittest.mock import Mock, patch

import pytest
import requests

from bnppf_rag_engine.rag_engine.sharepoint.api_client import (
    SharePointAPIClient,
)
from bnppf_rag_engine.rag_engine.sharepoint.sharepoint_config import (
    SharePointConfig,
)


class TestSharePointAPIClient:
    """Test SharePointAPIClient class."""

    @pytest.fixture
    def mock_config(self):
        """Create mock SharePoint config."""
        return SharePointConfig(
            crt_filepath="/path/to/cert.crt", key_filepath="/path/to/key.key", site_name="test_site"
        )

    @pytest.fixture
    def mock_authenticator(self):
        """Create mock authenticator."""
        authenticator = Mock()
        authenticator.get_access_token.return_value = "test_token"
        authenticator.get_proxies.return_value = {}
        return authenticator

    def test_build_url(self, mock_config, mock_authenticator):
        """Test URL building."""
        client = SharePointAPIClient(mock_config, mock_authenticator)

        url = client._build_url("/_api/web/lists")
        expected = "https://bnpparibas.sharepoint.com/sites/test_site/_api/web/lists"

        assert url == expected

    def test_build_url_with_leading_slash(self, mock_config, mock_authenticator):
        """Test URL building with leading slash in endpoint."""
        client = SharePointAPIClient(mock_config, mock_authenticator)

        url = client._build_url("/_api/web/lists")
        expected = "https://bnpparibas.sharepoint.com/sites/test_site/_api/web/lists"

        assert url == expected

    def test_get_headers(self, mock_config, mock_authenticator):
        """Test request headers generation."""
        client = SharePointAPIClient(mock_config, mock_authenticator)

        headers = client._get_headers()

        expected = {
            "Authorization": "Bearer test_token",
            "Accept": "application/json;odata=verbose",
            "Content-Type": "application/json;odata=verbose",
        }
        assert headers == expected

    @patch("bnppf_rag_engine.rag_engine.api_client.requests.get")
    def test_send_request_success(self, mock_get, mock_config, mock_authenticator):
        """Test successful API request."""
        # Setup mock response
        mock_response = Mock()
        mock_response.json.return_value = {"test": "data"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        client = SharePointAPIClient(mock_config, mock_authenticator)

        result = client.send_request("/_api/web/lists")

        assert result == {"test": "data"}
        mock_get.assert_called_once()

    @patch("bnppf_rag_engine.rag_engine.api_client.requests.get")
    def test_send_request_json_decode_error(self, mock_get, mock_config, mock_authenticator):
        """Test API request with JSON decode error."""
        # Setup mock response
        mock_response = Mock()
        mock_response.json.side_effect = requests.JSONDecodeError("msg", "doc", 0)
        mock_response.content = b"raw content"
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        client = SharePointAPIClient(mock_config, mock_authenticator)

        result = client.send_request("/_api/web/lists")

        assert result == {"content": b"raw content"}

    @patch("bnppf_rag_engine.rag_engine.api_client.requests.get")
    def test_send_request_connection_error(self, mock_get, mock_config, mock_authenticator):
        """Test API request with connection error."""
        mock_get.side_effect = requests.ConnectionError("Connection failed")

        client = SharePointAPIClient(mock_config, mock_authenticator)

        with pytest.raises(ConnectionError, match="Failed to send request"):
            client.send_request("/_api/web/lists")

    @patch("bnppf_rag_engine.rag_engine.api_client.requests.get")
    def test_download_file_success(self, mock_get, mock_config, mock_authenticator):
        """Test successful file download."""
        mock_response = Mock()
        mock_response.content = b"file content"
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        client = SharePointAPIClient(mock_config, mock_authenticator)

        content = client.download_file("/sites/test/document.docx")

        assert content == b"file content"

##Here is the original code;

"""SharePointAPIClient class."""

from typing import Any

import requests

from bnppf_rag_engine.rag_engine.sharepoint.authenticator import (
    SharePointAuthenticator,
)
from bnppf_rag_engine.rag_engine.sharepoint.sharepoint_config import (
    SharePointConfig,
)


class SharePointAPIClient:
    """Handles SharePoint API communication."""

    def __init__(self, sp_config: SharePointConfig, authenticator: SharePointAuthenticator):  # noqa: D107
        self.config = sp_config
        self.authenticator = authenticator

    def send_request(self, endpoint: str) -> dict[str, Any]:
        """Send request to SharePoint API."""
        headers = self._get_headers()
        url = self._build_url(endpoint)
        try:
            response = requests.get(
                url, headers=headers, proxies=self.authenticator.get_proxies(), verify=True, timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.JSONDecodeError:
            return {"content": response.content}
        except requests.RequestException as e:
            raise ConnectionError(f"Failed to send request to {url}: {e}") from e

    def download_file(self, server_relative_url: str) -> bytes:
        """Download file content from SharePoint."""
        endpoint = f"/_api/web/GetFileByServerRelativeUrl('{server_relative_url}')/$Value"
        headers = self._get_headers()
        url = self._build_url(endpoint)

        response = requests.get(url, headers=headers, proxies=self.authenticator.get_proxies(), verify=True, timeout=30)
        response.raise_for_status()
        return response.content

    def _get_headers(self) -> dict[str, str]:
        """Get request headers with authentication."""
        return {
            "Authorization": f"Bearer {self.authenticator.get_access_token()}",
            "Accept": "application/json;odata=verbose",
            "Content-Type": "application/json;odata=verbose",
        }

    def _build_url(self, endpoint: str) -> str:
        """Build complete URL for API endpoint."""
        clean_endpoint = endpoint.lstrip("/")
        return f"{self.config.site_base}/sites/{self.config.site_name}/{clean_endpoint}"
