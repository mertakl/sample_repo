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
        proxy_url = os.environ.get("PROXY")
        return {"http": proxy_url, "https": proxy_url} if proxy_url else {}

    def _initialize_azure_credentials(self) -> AzureCredentials:
        """Initialize Azure credentials."""
        tenant_id = os.environ.get("AZURE_TENANT_ID")
        if not tenant_id:
            raise ValueError("AZURE_TENANT_ID environment variable is required")

        return AzureCredentials.from_env(tenant_id, self.config.site_base)
