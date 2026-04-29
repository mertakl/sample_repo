def test_orchestrator_skips_metadata_on_download_failed(mocker, orchestrator, mock_document_fetcher, sharepoint_doc):
    """Test _process_all_documents method."""
    # Setup mocks
    mock_document = mocker.Mock(spec=SharepointDocument)
    mock_document.source = "eureka"
    mock_document.name = "test_doc1"

    mock_documents = [sharepoint_doc, mock_document]
    mock_document_fetcher.get_documents.return_value = mock_documents

    # Patch process_document on the actual doc_processor instance
    mocker.patch.object(
        orchestrator.doc_processor,
        "process_document",
        return_value=DownloadStatus.DOWNLOAD_FAILED
    )

    mocker.patch(
        "bnppf_rag_engine.sharepoint.orchestrator.failed_download_uid_from_last_successful_run",
        return_value=set()
    )

    orchestrator._process_all_documents(LIBRARIES_AND_SUBFOLDERS)

    orchestrator.doc_processor.metadata_manager.write_metadata.assert_not_called()
    orchestrator.doc_processor.flush_metadata_to_cos.assert_called_once_with({})
