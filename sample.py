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
        assert DocumentFilter.is_parseable("document.pdf")
        assert DocumentFilter.is_parseable("DOCUMENT.PDF")

    def test_is_parseable_invalid_extensions(self):
        """Test parseable file detection for invalid extensions."""
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
