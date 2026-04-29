def test_flush_metadata_to_cos(document_processor, mock_cos_api):
    """Test that metadata is saved to COS once per unique source path."""
    df1 = pd.DataFrame([{"uid": "doc1", "source": "eureka"}])
    df2 = pd.DataFrame([{"uid": "doc2", "source": "ineum"}])
    
    metadata_cache = {
        "path/to/eureka_metadata.csv": df1,
        "path/to/ineum_metadata.csv": df2,
    }

    document_processor.flush_metadata_to_cos(metadata_cache)

    assert document_processor.metadata_manager.save_metadata_on_cos.call_count == 2
    document_processor.metadata_manager.save_metadata_on_cos.assert_any_call(
        df_metadata=df1, cos_filepath="path/to/eureka_metadata.csv"
    )
    document_processor.metadata_manager.save_metadata_on_cos.assert_any_call(
        df_metadata=df2, cos_filepath="path/to/ineum_metadata.csv"
    )


def test_orchestrator_skips_metadata_on_download_failed(orchestrator, mock_doc_processor):
    """Test that metadata is not collected for failed documents."""
    mock_doc_processor.process_document.return_value = DownloadStatus.DOWNLOAD_FAILED
    mock_doc_processor.path_manager.get_source_metadata_path.return_value = "path/to/metadata.csv"
    mock_doc_processor.cos_api.file_exists.return_value = False

    orchestrator.process_documents(
        all_documents=[mock_document],
        failed_download_uids=set(),
    )

    # Metadata should not be written or flushed for failed documents
    mock_doc_processor.metadata_manager.write_metadata.assert_not_called()
    mock_doc_processor.flush_metadata_to_cos.assert_called_once_with({})  # empty cache
