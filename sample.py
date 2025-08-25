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
            crt_filepath="/path/to/cert.crt",
            key_filepath="/path/to/key.key",
            site_name="test_site",
            site_base="https://test.sharepoint.com"
        )

    @pytest.fixture
    def mock_authenticator(self):
        """Create mock authenticator."""
        authenticator = Mock()
        authenticator.get_access_token.return_value = "test_token"
        authenticator.get_proxies.return_value = {}
        return authenticator

    def test_build_url(self, mock_config, mock_authenticator):
        """Test URL building with and without a leading slash in the endpoint."""
        client = SharePointAPIClient(mock_config, mock_authenticator)

        # Test endpoint with a leading slash
        url_with_slash = client._build_url("/_api/web/lists")
        expected_with_slash = "https://test.sharepoint.com/sites/test_site/_api/web/lists"
        assert url_with_slash == expected_with_slash

        # Test endpoint without a leading slash
        url_without_slash = client._build_url("_api/web/lists")
        expected_without_slash = "https://test.sharepoint.com/sites/test_site/_api/web/lists"
        assert url_without_slash == expected_without_slash

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

    @patch("bnppf_rag_engine.rag_engine.sharepoint.api_client.requests.get")
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

    @patch("bnppf_rag_engine.rag_engine.sharepoint.api_client.requests.get")
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

    @patch("bnppf_rag_engine.rag_engine.sharepoint.api_client.requests.get")
    def test_send_request_connection_error(self, mock_get, mock_config, mock_authenticator):
        """Test API request with connection error."""
        mock_get.side_effect = requests.ConnectionError("Connection failed")

        client = SharePointAPIClient(mock_config, mock_authenticator)

        with pytest.raises(ConnectionError, match="Failed to send request"):
            client.send_request("/_api/web/lists")

    @patch("bnppf_rag_engine.rag_engine.sharepoint.api_client.requests.get")
    def test_download_file_success(self, mock_get, mock_config, mock_authenticator):
        """Test successful file download."""
        mock_response = Mock()
        mock_response.content = b"file content"
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        client = SharePointAPIClient(mock_config, mock_authenticator)

        content = client.download_file("/sites/test_site/document.docx")
        
        expected_url = "https://test.sharepoint.com/sites/test_site/_api/web/GetFileByServerRelativeUrl('/sites/test_site/document.docx')/$Value"
        expected_headers = {
            "Authorization": "Bearer test_token",
            "Accept": "application/json;odata=verbose",
            "Content-Type": "application/json;odata=verbose",
        }

        assert content == b"file content"
        mock_get.assert_called_once_with(
            expected_url,
            headers=expected_headers,
            proxies={},
            verify=True,
            timeout=30,
        )
