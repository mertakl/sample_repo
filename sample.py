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
            raise OSError("Failed to write metadata to %s: %s", metadata_path, str(e)) from e

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
            raise OSError("Failed to remove metadata from %s: %s", metadata_path, str(e)) from e

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

##Can you fix the test?


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

        # Fixed parameter order: file_name first, metadata_path second
        result = metadata_manager.get_metadata_by_filename("test.docx", "test_path.csv")

        # Verify the mock was called with correct parameters
        mock_cos_api.file_exists.assert_called_once_with("test_path.csv")
        mock_cos_api.read_csv.assert_called_once_with("test_path.csv", sep=";")

        assert result["file_name"] == "test.docx"
        assert result["url"] == "/test/test.docx"

    def test_get_metadata_by_filename_not_exists(self, metadata_manager, mock_cos_api):
        """Test getting metadata for non-existing file."""
        mock_cos_api.file_exists.return_value = False

        # Fixed parameter order: file_name first, metadata_path second
        result = metadata_manager.get_metadata_by_filename("test.docx", "test_path.csv")

        mock_cos_api.file_exists.assert_called_once_with("test_path.csv")
        # read_csv should not be called if file doesn't exist
        mock_cos_api.read_csv.assert_not_called()

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

        # Fixed parameter order: file_name first, metadata_path second
        result = metadata_manager.get_metadata_by_filename("test.docx", "test_path.csv")

        mock_cos_api.file_exists.assert_called_once_with("test_path.csv")
        mock_cos_api.read_csv.assert_called_once_with("test_path.csv", sep=";")

        assert result is None

    def test_get_metadata_by_filename_empty_data_error(self, metadata_manager, mock_cos_api):
        """Test handling of EmptyDataError."""
        mock_cos_api.file_exists.return_value = True
        mock_cos_api.read_csv.side_effect = pd.errors.EmptyDataError()

        result = metadata_manager.get_metadata_by_filename("test.docx", "test_path.csv")

        assert result is None

    def test_get_metadata_by_filename_key_error(self, metadata_manager, mock_cos_api):
        """Test handling of KeyError."""
        mock_cos_api.file_exists.return_value = True
        mock_cos_api.read_csv.side_effect = KeyError("file_name")

        result = metadata_manager.get_metadata_by_filename("test.docx", "test_path.csv")

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

        mock_cos_api.file_exists.assert_called_once_with("test_path.csv")
        # read_csv should not be called for new file
        mock_cos_api.read_csv.assert_not_called()
        mock_cos_api.df_to_csv.assert_called_once()

        # Verify the DataFrame passed to df_to_csv
        call_args = mock_cos_api.df_to_csv.call_args
        df_arg = call_args.kwargs["df"]
        assert df_arg.iloc[0]["file_name"] == "test.docx"
        assert call_args.kwargs["cos_filename"] == "test_path.csv"
        assert call_args.kwargs["header"] is True

    def test_write_metadata_existing_file_new_entry(self, metadata_manager, mock_cos_api):
        """Test writing metadata to existing CSV file with new entry."""
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

        mock_cos_api.file_exists.assert_called_once_with("test_path.csv")
        mock_cos_api.read_csv.assert_called_once_with("test_path.csv", sep=";")
        mock_cos_api.df_to_csv.assert_called_once()

        # Verify the DataFrame has both entries
        call_args = mock_cos_api.df_to_csv.call_args
        df_arg = call_args.kwargs["df"]
        assert len(df_arg) == 2  # Should have both entries

    def test_write_metadata_existing_file_update_entry(self, metadata_manager, mock_cos_api):
        """Test updating existing metadata entry."""
        existing_df = pd.DataFrame(
            [
                {
                    "file_name": "test.docx",
                    "url": "/test/old_url.docx",
                    "created_by": "old_user@example.com",
                    "last_modified": "2022-01-01T00:00:00Z",
                    "nota_number": "456",
                    "language": "FR",
                    "source": "test_source",  # Same source and file_name
                }
            ]
        )

        mock_cos_api.file_exists.return_value = True
        mock_cos_api.read_csv.return_value = existing_df

        metadata = DocumentMetadata(
            file_name="test.docx",
            url="/test/new_url.docx",
            created_by="new_user@example.com",
            last_modified="2023-01-01T00:00:00Z",
            nota_number="123",
            language="EN",
            source="test_source",  # Same source and file_name - should trigger update
        )

        metadata_manager.write_metadata(metadata, "test_path.csv")

        mock_cos_api.df_to_csv.assert_called_once()

        # Verify the entry was updated, not added
        call_args = mock_cos_api.df_to_csv.call_args
        df_arg = call_args.kwargs["df"]
        assert len(df_arg) == 1  # Should still be 1 entry (updated, not added)

    def test_write_metadata_os_error(self, metadata_manager, mock_cos_api):
        """Test handling of OSError during write."""
        mock_cos_api.file_exists.return_value = False
        mock_cos_api.df_to_csv.side_effect = OSError("Permission denied")

        metadata = DocumentMetadata(
            file_name="test.docx",
            url="/test/test.docx",
            created_by="user@example.com",
            last_modified="2023-01-01T00:00:00Z",
            nota_number="123",
            language="EN",
            source="test_source",
        )

        with pytest.raises(OSError, match="Failed to write metadata to test_path.csv"):
            metadata_manager.write_metadata(metadata, "test_path.csv")

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

        mock_cos_api.file_exists.assert_called_once_with("test_path.csv")
        mock_cos_api.read_csv.assert_called_once_with("test_path.csv", sep=";")
        mock_cos_api.df_to_csv.assert_called_once()

        # Verify only the other.docx entry remains
        call_args = mock_cos_api.df_to_csv.call_args
        df_arg = call_args.kwargs["df"]
        assert len(df_arg) == 1
        assert df_arg.iloc[0]["file_name"] == "other.docx"

    def test_remove_metadata_file_not_exists(self, metadata_manager, mock_cos_api):
        """Test removing metadata when CSV file doesn't exist."""
        mock_cos_api.file_exists.return_value = False

        metadata_manager.remove_metadata("test_path.csv", "test.docx")

        mock_cos_api.file_exists.assert_called_once_with("test_path.csv")
        mock_cos_api.read_csv.assert_not_called()
        mock_cos_api.df_to_csv.assert_not_called()

    def test_remove_metadata_empty_result(self, metadata_manager, mock_cos_api):
        """Test removing metadata when result would be empty."""
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
                }
            ]
        )

        mock_cos_api.file_exists.return_value = True
        mock_cos_api.read_csv.return_value = existing_df

        metadata_manager.remove_metadata("test_path.csv", "test.docx")

        # df_to_csv should not be called when result is empty
        mock_cos_api.df_to_csv.assert_not_called()

    def test_remove_metadata_os_error(self, metadata_manager, mock_cos_api):
        """Test handling of OSError during remove."""
        mock_cos_api.file_exists.return_value = True
        mock_cos_api.read_csv.side_effect = OSError("Permission denied")

        with pytest.raises(OSError, match="Failed to remove metadata from test_path.csv"):
            metadata_manager.remove_metadata("test_path.csv", "test.docx")
