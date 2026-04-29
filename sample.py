def test_orchestrator_skips_metadata_on_download_failed(orchestrator, mock_doc_processor):
    """Test that metadata is not collected for failed documents."""
    mock_doc_processor.process_document.return_value = DownloadStatus.DOWNLOAD_FAILED
    mock_doc_processor.path_manager = MagicMock()
    mock_doc_processor.path_manager.get_source_metadata_path.return_value = "path/to/metadata.csv"
    mock_doc_processor.cos_api = MagicMock()
    mock_doc_processor.cos_api.file_exists.return_value = False

    orchestrator.process_documents(
        all_documents=[mock_document],
        failed_download_uids=set(),
    )

    # Metadata should not be written or flushed for failed documents
    mock_doc_processor.metadata_manager.write_metadata.assert_not_called()
    mock_doc_processor.flush_metadata_to_cos.assert_called_once_with({})  # empty cache
