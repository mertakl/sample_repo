import os
from unittest.mock import Mock, mock_open, patch

import pytest

from bnppf_rag_engine.rag_engine.sharepoint.authenticator import (
    SharePointAuthenticator,
)
from bnppf_rag_engine.rag_engine.sharepoint.sharepoint_config import (
    AzureCredentials,
    SharePointConfig,
)


class TestSharePointAuthenticator:
    """Test SharePointAuthenticator class."""

    @pytest.fixture
    def mock_config(self):
        """Create mock SharePoint config."""
        return SharePointConfig(
            crt_filepath="/path/to/cert.crt",
            key_filepath="/path/to/key.key",
            site_name="test_site",
            site_base="https://test.sharepoint.com",
        )

    @pytest.fixture
    def mock_azure_creds(self):
        """Create mock AzureCredentials."""
        creds = Mock(spec=AzureCredentials)
        creds.thumbprint = "test_thumbprint"
        creds.client_id = "test_client_id"
        creds.authority = "https://login.microsoftonline.com/test_tenant"
        creds.scope = ["https://test.sharepoint.com/.default"]
        return creds

    @patch("bnppf_rag_engine.rag_engine.sharepoint.authenticator.AzureCredentials.from_env")
    @patch("builtins.open", mock_open(read_data="file_content"))
    def test_get_client_creds_initialization(self, mock_from_env, mock_config, mock_azure_creds):
        """Test client credentials are correctly created during initialization."""
        mock_from_env.return_value = mock_azure_creds

        with patch.dict(os.environ, {"AZURE_TENANT_ID": "test_tenant"}):
            authenticator = SharePointAuthenticator(mock_config)

        creds = authenticator.azure_creds.client_creds

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

    @patch("bnppf_rag_engine.rag_engine.sharepoint.authenticator.ConfidentialClientApplication")
    @patch("bnppf_rag_engine.rag_engine.sharepoint.authenticator.AzureCredentials.from_env")
    @patch("builtins.open", mock_open(read_data="file_content"))
    def test_get_access_token_success(self, mock_from_env, mock_app_class, mock_config, mock_azure_creds):
        """Test successful token acquisition via the public get_access_token method."""
        mock_from_env.return_value = mock_azure_creds

        mock_app = Mock()
        mock_app.acquire_token_for_client.return_value = {"access_token": "test_access_token"}
        mock_app_class.return_value = mock_app

        with patch.dict(os.environ, {"AZURE_TENANT_ID": "test_tenant"}):
            authenticator = SharePointAuthenticator(mock_config)
            token = authenticator.get_access_token()

        assert token == "test_access_token"
        mock_app.acquire_token_for_client.assert_called_once_with(scopes=mock_azure_creds.scope)

    @patch("bnppf_rag_engine.rag_engine.sharepoint.authenticator.ConfidentialClientApplication")
    @patch("bnppf_rag_engine.rag_engine.sharepoint.authenticator.AzureCredentials.from_env")
    @patch("builtins.open", mock_open(read_data="file_content"))
    def test_get_access_token_error(self, mock_from_env, mock_app_class, mock_config, mock_azure_creds):
        """Test token acquisition error via the public get_access_token method."""
        mock_from_env.return_value = mock_azure_creds

        mock_app = Mock()
        mock_app.acquire_token_for_client.return_value = {"error": "invalid_client"}
        mock_app_class.return_value = mock_app

        with patch.dict(os.environ, {"AZURE_TENANT_ID": "test_tenant"}):
            authenticator = SharePointAuthenticator(mock_config)
            with pytest.raises(ValueError, match="Error getting access token: %s"):
                authenticator.get_access_token()

    @patch("bnppf_rag_engine.rag_engine.sharepoint.authenticator.AzureCredentials.from_env")
    def test_initialization_missing_tenant_id(self, mock_from_env, mock_config):
        """Test initialization fails when AZURE_TENANT_ID is missing."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(KeyError):
                SharePointAuthenticator(mock_config)

    @patch("bnppf_rag_engine.rag_engine.sharepoint.authenticator.AzureCredentials.from_env")
    @patch("builtins.open", mock_open(read_data="file_content"))
    def test_initialization_empty_tenant_id(self, mock_from_env, mock_config, mock_azure_creds):
        """Test initialization fails when AZURE_TENANT_ID is empty."""
        mock_from_env.return_value = mock_azure_creds
        
        with patch.dict(os.environ, {"AZURE_TENANT_ID": ""}):
            with pytest.raises(ValueError, match="AZURE_TENANT_ID environment variable is required"):
                SharePointAuthenticator(mock_config)
