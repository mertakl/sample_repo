@pytest.fixture
def mock_doc_processor(mocker, path_manager):
    """Create mock document processor with realistic behavior."""
    processor = mocker.MagicMock(spec=DocumentProcessor)
    processor.logs_uid = "cos_update_logs.yaml"

    # Track processed documents (only those attempted for download)
    processor.downloaded_docs = []
    processor.download_status = {
        DownloadStatus.RECENTLY_MODIFIED: [],
        DownloadStatus.NEW_DOCUMENT: [],
        DownloadStatus.FILE_EXISTS_AND_NOT_MODIFIED: [],
        DownloadStatus.DOWNLOAD_FAILED: [],
        DownloadStatus.DOWNLOAD_FAILED_LAST_SUCCESSFUL_RUN: [],
    }

    def mock_get_document_status(document, failed_download_uids):
        """Simulate status check based on document name."""
        if "doc1" in document.name:
            return DownloadStatus.RECENTLY_MODIFIED
        elif "doc2" in document.name:
            return DownloadStatus.NEW_DOCUMENT
        elif "doc3" in document.name:
            return DownloadStatus.FILE_EXISTS_AND_NOT_MODIFIED
        elif "doc4" in document.name:
            return DownloadStatus.DOWNLOAD_FAILED_LAST_SUCCESSFUL_RUN
        else:
            raise ValueError(f"Document {document.name} is not managed inside mock.")

    def mock_download_and_upload(document):
        """Simulate download attempt — doc4 fails, others succeed."""
        processor.downloaded_docs.append(document)
        if "doc4" in document.name:
            processor.download_status[DownloadStatus.DOWNLOAD_FAILED].append(document.uid)
            return DownloadStatus.DOWNLOAD_FAILED
        elif "doc1" in document.name:
            processor.download_status[DownloadStatus.RECENTLY_MODIFIED].append(document.uid)
            return DownloadStatus.RECENTLY_MODIFIED
        elif "doc2" in document.name:
            processor.download_status[DownloadStatus.NEW_DOCUMENT].append(document.uid)
            return DownloadStatus.NEW_DOCUMENT

    def mock_write_file():
        with open(path_manager.sharepoint_path / "cos_update_logs.yaml", "w") as file:
            yaml.safe_dump(
                {status.value: processor.download_status[status] for status in DownloadStatus},
                file
            )

    processor.get_document_status.side_effect = mock_get_document_status
    processor.download_and_upload.side_effect = mock_download_and_upload
    processor.flush_metadata.return_value = None  # void, called once at end
    processor.write_log_files.side_effect = mock_write_file
    processor.path_manager = path_manager
    return processor


@pytest.mark.anyio
async def test_full_workflow_execution(
    orchestrator,
    mock_document_fetcher,
    mock_doc_processor,
    mock_db_manager,
    last_success_date,
    clean_today_v_sharepoint,
):
    """Test the complete workflow from document fetching to DB update."""
    # Logs with "yesterday's" data
    log_folder = orchestrator.path_manager.sharepoint_path.parent / last_success_date
    log_folder.mkdir(exist_ok=True, parents=True)
    log_data = {
        DownloadStatus.RECENTLY_MODIFIED.value: ["doc1.docx@BNPPF"],
        DownloadStatus.NEW_DOCUMENT.value: ["doc2.pdf@BNPPF"],
        DownloadStatus.FILE_EXISTS_AND_NOT_MODIFIED.value: ["doc3.docx@BNPPF"],
        DownloadStatus.DOWNLOAD_FAILED.value: ["doc4.docx@BNPPF"],
        DownloadStatus.DOWNLOAD_FAILED_LAST_SUCCESSFUL_RUN.value: [],
    }
    with open(log_folder / "cos_update_logs.yaml", "w") as f:
        yaml.safe_dump(log_data, f)

    # Execute the full workflow
    await orchestrator.run()

    # Verify document fetching
    assert mock_document_fetcher.get_documents_called

    # Verify status was checked for all documents
    assert mock_doc_processor.get_document_status.call_count == 4  # doc1,2,3,4

    # Verify only documents requiring download were attempted (doc1, doc2, doc4)
    assert len(mock_doc_processor.downloaded_docs) == 3
    downloaded_names = [doc.name for doc in mock_doc_processor.downloaded_docs]
    assert all(name in downloaded_names for name in ["doc1", "doc2", "doc4"])
    assert "doc3" not in downloaded_names  # FILE_EXISTS_AND_NOT_MODIFIED — skipped

    # Verify metadata was flushed once (not per document)
    mock_doc_processor.flush_metadata.assert_called_once()

    # Verify log files written once
    mock_doc_processor.write_log_files.assert_called_once()

    # Verify DB updates for all languages
    assert len(mock_db_manager.updated_languages) == len(LANGUAGE_MAPPING.values())
    for language in LANGUAGE_MAPPING.values():
        assert language in mock_db_manager.updated_languages
