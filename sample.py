Can you fix the following sonar issues in the following code?
###Issues

def __init__(self, cos_api, csv_file_name: str = "sharepoint_metadata.csv"):  # noqa: D107
Define a constant instead of duplicating this literal "sharepoint_metadata.csv" 3 times.
----------
def __init__(self, config: "SharePointConfig", azure_creds: "AzureCredentials"):  # noqa: D107
Redefining name 'config' from outer scope (line 545) (Some other parts as well)

 @staticmethod
    def _get_proxies() -> dict[str, str]:
        """Get proxy configuration."""
        proxy = os.getenv("PROXY")
        return {"http": proxy, "https": proxy} if proxy else {}
Redefining name 'args' from outer scope (line 374) (Some other parts as well)
----------------

except Exception as e:
Catching too general exception Exception (Another part as well)

-------------

if __name__ == "__main__":
    """Runs sharepoint_client with args."""
String statement has no effect

-------------
    except Exception as e:
            logger.error("Failed to process deleted files: %s", e)
            pass
Remove this unneeded "pass".

###End Issues
"""This module provides utilities for connecting Sharepoint."""

import argparse
import logging
import os
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv
from msal import ConfidentialClientApplication

from bnppf_rag_engine.config.utils import CONFIGS, get_or_raise_config
from bnppf_rag_engine.constants.constants import AVAILABLE_LANGUAGES
from bnppf_rag_engine.cos.bucket_interaction import create_cos_api
from bnppf_rag_engine.rag_engine.document_parser import DocumentParser

logger = logging.getLogger(__name__)

load_dotenv()


@dataclass
class SharePointConfig:
    """Sharepoint config dataclass."""

    crt_filepath: str
    key_filepath: str
    site_name: str
    site_base: str = "https://bnpparibas.sharepoint.com"


@dataclass
class AzureCredentials:
    """Azure credientals dataclass."""

    client_id: str
    tenant_id: str
    authority: str
    scope: list
    thumbprint: str
    client_creds: dict

    @classmethod
    def from_env(cls, tenant_id: str, site_base: str) -> "AzureCredentials":
        """Create Azure credentials from environment variables."""
        client_id = os.getenv("AZURE_CLIENT_ID")
        scope = [f"{site_base}/.default"]
        authority = f"https://login.microsoftonline.com/{tenant_id}"
        thumbprint = os.getenv("THUMBPRINT")

        client_creds = {}

        return cls(
            client_id=client_id,
            tenant_id=tenant_id,
            authority=authority,
            scope=scope,
            thumbprint=thumbprint,
            client_creds=client_creds,
        )


@dataclass
class DocumentMetadata:
    """Data class for document metadata."""

    file_name: str
    url: str
    created_by: str | None
    last_modified: str
    nota_number: str | None
    language: str
    source: str


@dataclass
class ProcessedDocument:
    """Data class for processed document information."""

    file: dict[str, Any]
    nota_number: str | None
    source: str
    language: str


class SharePointAuthenticator:
    """Handles SharePoint authentication logic."""

    def __init__(self, config: "SharePointConfig", azure_creds: "AzureCredentials"):  # noqa: D107
        self.config = config
        self.azure_creds = azure_creds
        self.azure_creds.client_creds = self._get_client_creds()
        self._access_token: str | None = None

    def get_access_token(self) -> str:
        """Get or refresh access token."""
        if not self._access_token:
            self._access_token = self._acquire_token()
        return self._access_token

    def _acquire_token(self) -> str:
        """Acquire access token from Azure."""
        proxies = self._get_proxies()

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
    def _get_proxies() -> dict[str, str]:
        """Get proxy configuration."""
        proxy = os.getenv("PROXY")
        return {"http": proxy, "https": proxy} if proxy else {}


class SharePointAPIClient:
    """Handles SharePoint API communication."""

    def __init__(self, config: "SharePointConfig", authenticator: SharePointAuthenticator):  # noqa: D107
        self.config = config
        self.authenticator = authenticator

    def send_request(self, endpoint: str) -> dict[str, Any]:
        """Send request to SharePoint API."""
        headers = self._get_headers()
        url = self._build_url(endpoint)

        try:
            response = requests.get(
                url, headers=headers, proxies=self.authenticator._get_proxies(), verify=True, timeout=30
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

        response = requests.get(
            url, headers=headers, proxies=self.authenticator._get_proxies(), verify=True, timeout=30
        )
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


class DocumentFilter:
    """Handles document filtering logic."""

    PARSEABLE_EXTENSIONS = {".doc", ".docx"}  # noqa: RUF012

    @staticmethod
    def is_parseable(file_name: str) -> bool:
        """Check if document is parseable."""
        _, extension = os.path.splitext(file_name)
        return extension.lower() in DocumentFilter.PARSEABLE_EXTENSIONS

    @staticmethod
    def is_recently_modified(last_modified_str: str, hours: int = 24) -> bool:
        """Check if document was modified within specified hours."""
        try:
            last_modified = DocumentFilter._parse_datetime(last_modified_str)
            current_time = datetime.now(timezone.utc)
            time_difference = current_time - last_modified
            return time_difference < timedelta(hours=hours)
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _parse_datetime(datetime_str: str) -> datetime:
        """Parse datetime string to datetime object."""
        if datetime_str.endswith("Z"):
            datetime_str = datetime_str[:-1] + "+00:00"
        return datetime.fromisoformat(datetime_str)


class MetadataManager:
    """Manages CSV metadata operations."""

    def __init__(self, cos_api, csv_file_name: str = "sharepoint_metadata.csv"):  # noqa: D107
        self.cos_api = cos_api
        self.csv_file_name = csv_file_name

    def get_metadata_by_filename(self, csv_path: str, file_name: str) -> dict[str, Any] | None:
        """Get metadata for specific file."""
        if not self.cos_api.file_exists(csv_path):
            return None

        try:
            df = self.cos_api.read_csv(csv_path, sep=";")
            filtered_df = df[df["file_name"] == file_name]
            return filtered_df.iloc[0].to_dict() if not filtered_df.empty else None
        except Exception:
            return None

    def write_metadata(self, metadata: DocumentMetadata, csv_path: str) -> None:
        """Write metadata to CSV file."""
        try:
            if self.cos_api.file_exists(csv_path):
                existing_df = self.cos_api.read_csv(csv_path, sep=";")
            else:
                existing_df = self._create_empty_dataframe()

            new_entry = pd.DataFrame([metadata.__dict__])
            updated_df = self._merge_metadata(existing_df, new_entry)

            self.cos_api.df_to_csv(df=updated_df, cos_filename=csv_path, header=True)

        except Exception as e:
            raise OSError(f"Failed to write metadata to {csv_path}: {e}") from e

    def remove_metadata(self, csv_path: str, file_name: str) -> None:
        """Remove metadata for specific file."""
        if not self.cos_api.file_exists(csv_path):
            return

        try:
            df = self.cos_api.read_csv(csv_path, sep=";")
            updated_df = df[df["file_name"] != file_name]

            if not updated_df.empty:
                self.cos_api.df_to_csv(df=updated_df, cos_filename=csv_path, header=True)

        except Exception as e:
            raise OSError(f"Failed to remove metadata from {csv_path}: {e}") from e

    @staticmethod
    def _create_empty_dataframe() -> pd.DataFrame:
        """Create empty DataFrame with proper columns."""
        columns = ["file_name", "url", "created_by", "last_modified", "nota_number", "language", "source"]
        return pd.DataFrame(columns=columns)

    @staticmethod
    def _merge_metadata(existing_df: pd.DataFrame, new_entry: pd.DataFrame) -> pd.DataFrame:
        """Merge new metadata entry with existing data."""
        unique_cols = ["file_name", "source"]
        mask = existing_df[unique_cols].eq(new_entry[unique_cols].iloc[0]).all(axis=1)

        if not existing_df[mask].empty:
            existing_df.update(new_entry)
            return existing_df
        else:
            return pd.concat([existing_df, new_entry], ignore_index=True)


class DocumentProcessor:
    """Processes SharePoint documents."""

    def __init__(self, api_client: SharePointAPIClient, cos_api, metadata_manager: MetadataManager):  # noqa: D107
        self.api_client = api_client
        self.cos_api = cos_api
        self.metadata_manager = metadata_manager

    def process_document(self, doc: ProcessedDocument, cos_folder_path: Path) -> None:
        """Process a single document."""
        file_info = doc.file
        file_name = file_info.get("Name", "")

        if not DocumentFilter.is_parseable(file_name):
            self._log_unparseable_document(file_name, doc)
            return

        last_modified = file_info.get("TimeLastModified", "")
        if not DocumentFilter.is_recently_modified(last_modified):
            return

        self._upload_document(doc, cos_folder_path)

    def delete_document(self, file_name: str, cos_folder_path: Path) -> None:
        """Delete document from COS and update metadata."""
        csv_path = str(cos_folder_path / "sharepoint_metadata.csv")
        metadata = self.metadata_manager.get_metadata_by_filename(csv_path, file_name)

        if not metadata:
            return

        # Delete file from COS
        file_path = cos_folder_path / metadata["source"] / metadata["language"] / file_name
        self.cos_api.delete_file(str(file_path))

        # Remove from metadata
        self.metadata_manager.remove_metadata(csv_path, file_name)

    def _upload_document(self, doc: ProcessedDocument, cos_folder_path: Path) -> None:
        """Upload document to COS and save metadata."""
        file_info = doc.file
        file_name = file_info["Name"]
        server_relative_url = file_info["ServerRelativeUrl"]

        # Download file content
        file_content = self.api_client.download_file(server_relative_url)

        # Create temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_name)[1]) as temp_file:
            temp_file.write(file_content)
            temp_file_path = temp_file.name

        try:
            # Upload to COS
            destination_path = cos_folder_path / doc.source / doc.language / file_name
            self.cos_api.upload_file(temp_file_path, str(destination_path))

            # Save metadata
            metadata = DocumentMetadata(
                file_name=file_name,
                url=server_relative_url,
                created_by=file_info.get("Author"),
                last_modified=file_info["TimeLastModified"],
                nota_number=doc.nota_number,
                language=doc.language,
                source=doc.source,
            )

            csv_path = str(cos_folder_path / "sharepoint_metadata.csv")
            self.metadata_manager.write_metadata(metadata, csv_path)

        finally:
            # Clean up temporary file
            os.unlink(temp_file_path)

    def _log_unparseable_document(self, file_name: str, doc: ProcessedDocument) -> None:
        """Log unparseable document."""
        DocumentParser.write_unparsed_docs(
            unparsable_docs=[file_name],
            source=doc.get("Source", "eureka"),
            language=doc.get("Language", "fr"),
            project_name=args.project_name,
        )

        _, extension = os.path.splitext(file_name)
        logger.error("Files with extension '%s' are not supported", extension)


class SharePointClient:
    """Main SharePoint client class."""

    def __init__(self, config: "SharePointConfig"):  # noqa: D107
        self.config = config
        self.cos_api = self._create_cos_api()

        # Initialize components
        self.azure_creds = self._initialize_azure_credentials()
        self.authenticator = SharePointAuthenticator(config, self.azure_creds)
        self.api_client = SharePointAPIClient(config, self.authenticator)
        self.metadata_manager = MetadataManager(self.cos_api)
        self.document_processor = DocumentProcessor(self.api_client, self.cos_api, self.metadata_manager)

    def run(self, args) -> None:
        """Main execution method."""
        config_handler = self._get_config_handler(args.project_name)
        languages = self._get_languages(args, config_handler)
        cos_folder_path = Path(config_handler.get_config("document_parser")["document_object_cos_folder"])

        # Handle deleted files
        self._process_deleted_files(cos_folder_path)

        # Process documents by language
        grouped_documents = self._get_grouped_documents(["Documents"])

        for language in languages:
            documents = grouped_documents.get(language, {})
            self._process_documents_by_language(documents, cos_folder_path)

    def _process_deleted_files(self, cos_folder_path: Path) -> None:
        """Process deleted files from recycle bin."""
        try:
            deleted_files = self._get_deleted_file_names()
            for file_name in deleted_files:
                self.document_processor.delete_document(file_name, cos_folder_path)
        except Exception as e:
            logger.error("Failed to process deleted files: %s", e)
            pass

    def _process_documents_by_language(self, documents_by_source: dict[str, list[dict]], cos_folder_path: Path) -> None:
        """Process documents grouped by source for a specific language."""
        for source, doc_list in documents_by_source.items():
            for doc_data in doc_list:
                doc = ProcessedDocument(
                    file=doc_data["File"],
                    nota_number=doc_data.get("NotaNumber"),
                    source=source,
                    language=doc_data.get("Language", ""),
                )
                self.document_processor.process_document(doc, cos_folder_path)

    def _get_grouped_documents(self, libraries: list[str]) -> dict[str, dict[str, list[dict]]]:
        """Get documents grouped by language and source."""
        grouped_documents = defaultdict(lambda: defaultdict(list))

        for library in libraries:
            try:
                documents = self._retrieve_documents_from_library(library)
                for doc in documents:
                    language = doc.get("Language")
                    source = doc.get("Source")
                    if language and source:
                        grouped_documents[language][source].append(doc)
            except Exception as e:
                logger.error("Error processing library %s: %s", library, e)
                continue

        return grouped_documents

    def _retrieve_documents_from_library(self, library_name: str) -> list[dict[str, Any]]:
        """Retrieve documents from specific SharePoint library."""
        endpoint = f"/_api/web/lists/GetByTitle('{library_name}')/items?$select=*&$expand=File"
        response = self.api_client.send_request(endpoint)

        items = response.get("d", {}).get("results", [])
        return [
            {
                "File": item.get("File", {}),
                "NotaNumber": item.get("notanumber"),
                "Source": item.get("source"),
                "Language": item.get("language"),
            }
            for item in items
        ]

    def _get_deleted_file_names(self) -> list[str]:
        """Get list of deleted file names from recycle bin."""
        try:
            response = self.api_client.send_request("/_api/site/RecycleBin?$filter=ItemState eq 1")
            deleted_documents = response.get("d", {}).get("results", [])
            return [doc.get("Title", "") for doc in deleted_documents if doc.get("Title")]
        except Exception:
            return []

    def _initialize_azure_credentials(self) -> "AzureCredentials":
        """Initialize Azure credentials."""
        tenant_id = os.getenv("AZURE_TENANT_ID")
        if not tenant_id:
            raise ValueError("AZURE_TENANT_ID environment variable is required")

        return AzureCredentials.from_env(tenant_id, self.config.site_base)

    @staticmethod
    def _create_cos_api():
        """Create COS API instance."""
        return create_cos_api()

    @staticmethod
    def _get_config_handler(project_name: str):
        """Get configuration handler."""
        return get_or_raise_config(project_name)

    @staticmethod
    def _get_languages(args, config_handler) -> list[str]:
        """Get list of languages to process."""
        if hasattr(args, "language") and args.language:
            return [args.language]
        return config_handler.get_config("languages")


def commandline_parser() -> argparse.ArgumentParser:
    """CMD parser."""
    parser = argparse.ArgumentParser(
        "Retrieve sharepoint documents",
        description="The command to retrieve documents from sharepoint and upload to COS",
    )

    parser.add_argument(
        "--language",
        type=str,
        default=None,
        choices=AVAILABLE_LANGUAGES,
        help="Specific language you want to test the DB with. Default use all languages.",
    )

    parser.add_argument(
        "--project_name",
        type=str,
        choices=CONFIGS,
        help="Name of the project.Used for configuration and path purposes.",
    )

    return parser


if __name__ == "__main__":
    """Runs sharepoint_client with args."""
    args = commandline_parser().parse_args()

    # Initialize the SharePointClient
    crt_content = os.getenv("SHAREPOINT_TLS_CERTIFICATE").replace("\\n", "\n")
    key_content = os.getenv("SHAREPOINT_TLS_KEY").replace("\\n", "\n")

    with tempfile.NamedTemporaryFile("w", suffix=".crt", delete=False) as crt_file:
        crt_file.write(crt_content)
        crt_path = crt_file.name

    with tempfile.NamedTemporaryFile("w", suffix=".key", delete=False) as key_file:
        key_file.write(key_content)
        key_path = key_file.name

    config = SharePointConfig(crt_filepath=crt_path, key_filepath=key_path, site_name="EurekaTestSite")

    sharepoint_client = SharePointClient(config)

    sharepoint_client.run(args=args)

    os.unlink(key_path)
    os.unlink(crt_path)



