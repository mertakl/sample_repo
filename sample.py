##Also this? 

from datetime import datetime, timedelta, timezone

from bnppf_rag_engine.rag_engine.sharepoint.document_filter import (
    DocumentFilter,
)


class TestDocumentFilter:
    """Test DocumentFilter class."""

    def test_is_parseable_valid_extensions(self):
        """Test parseable file detection for valid extensions."""
        assert DocumentFilter.is_parseable("document.doc")
        assert DocumentFilter.is_parseable("document.docx")
        assert DocumentFilter.is_parseable("DOCUMENT.DOC")
        assert DocumentFilter.is_parseable("DOCUMENT.DOCX")

    def test_is_parseable_invalid_extensions(self):
        """Test parseable file detection for invalid extensions."""
        assert not DocumentFilter.is_parseable("document.pdf")
        assert not DocumentFilter.is_parseable("document.txt")
        assert not DocumentFilter.is_parseable("document.xlsx")
        assert not DocumentFilter.is_parseable("document")

    def test_is_recently_modified_recent_file(self):
        """Test recent modification detection for recent files."""
        recent_time = datetime.now(timezone.utc) - timedelta(hours=12)
        time_str = recent_time.isoformat().replace("+00:00", "Z")

        assert DocumentFilter.is_recently_modified(time_str, hours=24)

    def test_is_recently_modified_old_file(self):
        """Test recent modification detection for old files."""
        old_time = datetime.now(timezone.utc) - timedelta(hours=48)
        time_str = old_time.isoformat().replace("+00:00", "Z")

        assert not DocumentFilter.is_recently_modified(time_str, hours=24)

##Original code;

"""DocumentFilter class."""

import os
from datetime import datetime, timedelta, timezone


class DocumentFilter:
    """Handles document filtering logic."""

    PARSEABLE_EXTENSIONS = {".doc", ".docx", ".pdf"}  # noqa: RUF012

    @staticmethod
    def is_parseable(file_name: str) -> bool:
        """Check if document is parseable."""
        _, extension = os.path.splitext(file_name)
        return extension.lower() in DocumentFilter.PARSEABLE_EXTENSIONS

    @staticmethod
    def is_recently_modified(last_modified_str: str, hours: int = 24) -> bool:
        # TODO: update docstring
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


