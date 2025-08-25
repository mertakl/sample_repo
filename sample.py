##Also this? 

from unittest.mock import Mock

import pandas as pd
import pytest

from bnppf_rag_engine.rag_engine.sharepoint.metadata_manager import (
    MetadataManager,
)
from bnppf_rag_engine.rag_engine.sharepoint.sharepoint_config import (
    DocumentMetadata,
)


class TestMetadataManager:
    """Test MetadataManager class."""

    @pytest.fixture
    def mock_cos_api(self):
        """Create mock COS API."""
        return Mock()

    @pytest.fixture
    def metadata_manager(self, mock_cos_api):
        """Create MetadataManager instance."""
        return MetadataManager(mock_cos_api)

    def test_get_metadata_by_filename_exists(self, metadata_manager, mock_cos_api):
        """Test getting metadata for existing file."""
        # Setup mock data
        test_df = pd.DataFrame(
            [
                {
                    "file_name": "test.docx",
                    "url": "/test/test.docx",
                    "created_by": "user@example.com",
                    "last_modified": "2023-01-01T00:00:00Z",
                    "nota_number": "123",
                    "language": "EN",
                    "source": "test_source",
                }
            ]
        )

        mock_cos_api.file_exists.return_value = True
        mock_cos_api.read_csv.return_value = test_df

        result = metadata_manager.get_metadata_by_filename("test_path.csv", "test.docx")

        assert result["file_name"] == "test.docx"
        assert result["url"] == "/test/test.docx"

    def test_get_metadata_by_filename_not_exists(self, metadata_manager, mock_cos_api):
        """Test getting metadata for non-existing file."""
        mock_cos_api.file_exists.return_value = False

        result = metadata_manager.get_metadata_by_filename("test_path.csv", "test.docx")

        assert result is None

    def test_get_metadata_by_filename_file_not_found(self, metadata_manager, mock_cos_api):
        """Test getting metadata when file is not in CSV."""
        test_df = pd.DataFrame(
            [
                {
                    "file_name": "other.docx",
                    "url": "/test/other.docx",
                    "created_by": "user@example.com",
                    "last_modified": "2023-01-01T00:00:00Z",
                    "nota_number": "123",
                    "language": "EN",
                    "source": "test_source",
                }
            ]
        )

        mock_cos_api.file_exists.return_value = True
        mock_cos_api.read_csv.return_value = test_df

        result = metadata_manager.get_metadata_by_filename("test_path.csv", "test.docx")

        assert result is None

    def test_write_metadata_new_file(self, metadata_manager, mock_cos_api):
        """Test writing metadata for new CSV file."""
        mock_cos_api.file_exists.return_value = False

        metadata = DocumentMetadata(
            file_name="test.docx",
            url="/test/test.docx",
            created_by="user@example.com",
            last_modified="2023-01-01T00:00:00Z",
            nota_number="123",
            language="EN",
            source="test_source",
        )

        metadata_manager.write_metadata(metadata, "test_path.csv")

        mock_cos_api.df_to_csv.assert_called_once()

    def test_write_metadata_existing_file(self, metadata_manager, mock_cos_api):
        """Test writing metadata to existing CSV file."""
        existing_df = pd.DataFrame(
            [
                {
                    "file_name": "other.docx",
                    "url": "/test/other.docx",
                    "created_by": "user@example.com",
                    "last_modified": "2023-01-01T00:00:00Z",
                    "nota_number": "456",
                    "language": "FR",
                    "source": "other_source",
                }
            ]
        )

        mock_cos_api.file_exists.return_value = True
        mock_cos_api.read_csv.return_value = existing_df

        metadata = DocumentMetadata(
            file_name="test.docx",
            url="/test/test.docx",
            created_by="user@example.com",
            last_modified="2023-01-01T00:00:00Z",
            nota_number="123",
            language="EN",
            source="test_source",
        )

        metadata_manager.write_metadata(metadata, "test_path.csv")

        mock_cos_api.df_to_csv.assert_called_once()

    def test_remove_metadata(self, metadata_manager, mock_cos_api):
        """Test removing metadata."""
        existing_df = pd.DataFrame(
            [
                {
                    "file_name": "test.docx",
                    "url": "/test/test.docx",
                    "created_by": "user@example.com",
                    "last_modified": "2023-01-01T00:00:00Z",
                    "nota_number": "123",
                    "language": "EN",
                    "source": "test_source",
                },
                {
                    "file_name": "other.docx",
                    "url": "/test/other.docx",
                    "created_by": "user@example.com",
                    "last_modified": "2023-01-01T00:00:00Z",
                    "nota_number": "456",
                    "language": "FR",
                    "source": "other_source",
                },
            ]
        )

        mock_cos_api.file_exists.return_value = True
        mock_cos_api.read_csv.return_value = existing_df

        metadata_manager.remove_metadata("test_path.csv", "test.docx")

        mock_cos_api.df_to_csv.assert_called_once()



##Original code;

"""MetadataManager class."""

import logging
from typing import Any

import pandas as pd
from bnppf_cos import CosBucketApi

from bnppf_rag_engine.rag_engine.sharepoint.sharepoint_config import (
    DocumentMetadata,
)

logger = logging.getLogger(__name__)


class MetadataManager:
    """Manages CSV metadata operations."""

    def __init__(self, cos_api: CosBucketApi):  # noqa: D107
        self.cos_api = cos_api

    def get_metadata_by_filename(self, file_name: str, metadata_path: str) -> dict[str, Any] | None:
        """Get metadata for specific file."""
        if not self.cos_api.file_exists(metadata_path):
            return None

        try:
            df = self.cos_api.read_csv(metadata_path, sep=";")
            filtered_df = df[df["file_name"] == file_name]
            return filtered_df.iloc[0].to_dict() if not filtered_df.empty else None
        except (pd.errors.EmptyDataError, KeyError, IndexError):
            return None

    def write_metadata(self, metadata: DocumentMetadata, metadata_path: str) -> None:
        """Write metadata to CSV file."""
        try:
            logger.info("Writing metadata information...")
            if self.cos_api.file_exists(metadata_path):
                existing_df = self.cos_api.read_csv(metadata_path, sep=";")
            else:
                existing_df = self._create_empty_dataframe()

            new_entry = pd.DataFrame([metadata.__dict__])
            updated_df = self._merge_metadata(existing_df, new_entry)

            self.cos_api.df_to_csv(df=updated_df, cos_filename=metadata_path, header=True)

        except (OSError, pd.errors.ParserError) as e:
            raise OSError(f"Failed to write metadata to {metadata_path}: {e}") from e

    def remove_metadata(self, metadata_path: str, file_name: str) -> None:
        """Remove metadata for specific file."""
        if not self.cos_api.file_exists(metadata_path):
            return

        try:
            logger.info("Removing metadata information for %s...", file_name)

            df = self.cos_api.read_csv(metadata_path, sep=";")
            updated_df = df[df["file_name"] != file_name]

            if not updated_df.empty:
                self.cos_api.df_to_csv(df=updated_df, cos_filename=metadata_path, header=True)

        except (OSError, pd.errors.ParserError) as e:
            raise OSError(f"Failed to remove metadata from {metadata_path}: {e}") from e

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

        logging.info("No update on medata file as nothing changed on it.")

        return pd.concat([existing_df, new_entry], ignore_index=True)


