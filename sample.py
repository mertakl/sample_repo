##Also this? 

import os
from unittest.mock import Mock, mock_open, patch

import pytest

from bnppf_rag_engine.rag_engine.sharepoint.authenticator import (
    SharePointAuthenticator,
)
from bnppf_rag_engine.rag_engine.sharepoint.sharepoint_config import (
    SharePointConfig,
)


class TestSharePointAuthenticator:
    """Test SharePointAuthenticator class."""

    @pytest.fixture
    def mock_config(self):
        """Create mock SharePoint config."""
        return SharePointConfig(
            crt_filepath="/path/to/cert.crt", key_filepath="/path/to/key.key", site_name="test_site"
        )

    @patch("builtins.open", mock_open(read_data="file_content"))
    def test_get_client_creds(self, mock_config, mock_azure_creds):
        """Test client credentials retrieval."""
        authenticator = SharePointAuthenticator(mock_config, mock_azure_creds)

        creds = authenticator._get_client_creds()

        assert creds["private_key"] == "file_content"
        assert creds["thumbprint"] == "test_thumbprint"
        assert creds["public_certificate"] == "file_content"

    @patch.dict(os.environ, {"PROXY": "http://proxy.example.com"})
    def test_get_proxies_with_proxy(self):
        """Test proxy configuration when PROXY env var is set."""
        proxies = SharePointAuthenticator.get_proxies()

        expected = {"http": "http://proxy.example.com", "https": "http://proxy.example.com"}
        assert proxies == expected

    @patch.dict(os.environ, {}, clear=True)
    def test_get_proxies_without_proxy(self):
        """Test proxy configuration when PROXY env var is not set."""
        proxies = SharePointAuthenticator.get_proxies()
        assert proxies == {}

    @patch("bnppf_rag_engine.rag_engine.sharepoint_client.ConfidentialClientApplication")
    @patch("builtins.open", mock_open(read_data="file_content"))
    def test_acquire_token_success(self, mock_app_class, mock_config):
        """Test successful token acquisition."""
        # Setup mocks
        mock_app = Mock()
        mock_app.acquire_token_for_client.return_value = {"access_token": "test_access_token"}
        mock_app_class.return_value = mock_app

        authenticator = SharePointAuthenticator(mock_config)

        token = authenticator._acquire_token()

        assert token == "test_access_token"
        mock_app.acquire_token_for_client.assert_called_once()

    @patch("bnppf_rag_engine.rag_engine.authenticator.ConfidentialClientApplication")
    @patch("builtins.open", mock_open(read_data="file_content"))
    def test_acquire_token_error(self, mock_app_class, mock_config, mock_azure_creds):
        """Test token acquisition with error response."""
        # Setup mocks
        mock_app = Mock()
        mock_app.acquire_token_for_client.return_value = {"error": "invalid_client"}
        mock_app_class.return_value = mock_app

        authenticator = SharePointAuthenticator(mock_config, mock_azure_creds)

        with pytest.raises(ValueError, match="Error getting access token"):
            authenticator._acquire_token()

##Original code;

"""SharePointAuthenticator class."""

import os

from msal import ConfidentialClientApplication

from bnppf_rag_engine.rag_engine.sharepoint.sharepoint_config import (
    AzureCredentials,
    SharePointConfig,
)


class SharePointAuthenticator:
    """Handles SharePoint authentication logic."""

    def __init__(self, sp_config: SharePointConfig):  # noqa: D107
        self.config = sp_config
        self.azure_creds = self._initialize_azure_credentials()
        self.azure_creds.client_creds = self._get_client_creds()
        self._access_token: str | None = None

    def get_access_token(self) -> str:
        """Get or refresh access token."""
        if not self._access_token:
            self._access_token = self._acquire_token()
        return self._access_token

    def _acquire_token(self) -> str:
        """Acquire access token from Azure."""
        proxies = self.get_proxies()

        app = ConfidentialClientApplication(
            client_id=self.azure_creds.client_id,
            authority=self.azure_creds.authority,
            client_credential=self.azure_creds.client_creds,
            proxies=proxies,
            verify=False,
        )

        token_response = app.acquire_token_for_client(scopes=self.azure_creds.scope)

        if "error" in token_response:
            raise ValueError(f"Error getting access token: {token_response['error']}")

        return token_response["access_token"]

    @staticmethod
    def _read_file(file_path: str) -> str:
        with open(file_path) as f:
            return f.read()

    def _get_client_creds(self) -> dict:
        key_data = self._read_file(self.config.key_filepath)
        public_cert = self._read_file(self.config.crt_filepath)
        return {
            "private_key": key_data,
            "thumbprint": self.azure_creds.thumbprint,
            "public_certificate": public_cert,
        }

    @staticmethod
    def get_proxies() -> dict[str, str]:
        """Get proxy configuration."""
        proxy_url = os.environ["PROXY"]
        return {"http": proxy_url, "https": proxy_url} if proxy_url else {}

    def _initialize_azure_credentials(self) -> AzureCredentials:
        """Initialize Azure credentials."""
        tenant_id = os.environ["AZURE_TENANT_ID"]
        if not tenant_id:
            raise ValueError("AZURE_TENANT_ID environment variable is required")

        return AzureCredentials.from_env(tenant_id, self.config.site_base)
