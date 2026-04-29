def test_orchestrator_collects_metadata_on_success(mocker, orchestrator, mock_document_fetcher, sharepoint_doc):
    """Test that metadata is collected and COS is checked once per source path on success."""
    mock_document = mocker.Mock(spec=SharepointDocument)
    mock_document.source = "eureka"
    mock_document.name = "test_doc1"

    mock_documents = [sharepoint_doc, mock_document]
    mock_document_fetcher.get_documents.return_value = mock_documents

    mocker.patch.object(
        orchestrator.doc_processor,
        "process_document",
        return_value=DownloadStatus.NEW_DOCUMENT
    )

    mocker.patch(
        "bnppf_rag_engine.sharepoint.orchestrator.failed_download_uid_from_last_successful_run",
        return_value=set()
    )

    metadata_path = "path/to/eureka_metadata.csv"
    orchestrator.doc_processor.path_manager.get_source_metadata_path.return_value = metadata_path
    orchestrator.doc_processor.cos_api.file_exists.return_value = False

    orchestrator._process_all_documents(LIBRARIES_AND_SUBFOLDERS)

    # file_exists called once per unique source path, not once per document
    orchestrator.doc_processor.cos_api.file_exists.assert_called_once_with(metadata_path)
    orchestrator.doc_processor.metadata_manager.write_metadata.assert_called()
    orchestrator.doc_processor.flush_metadata_to_cos.assert_called_once()
