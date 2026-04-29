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
    
    calls = document_processor.metadata_manager.save_metadata_on_cos.call_args_list
    assert calls[0].kwargs["cos_filepath"] == "path/to/eureka_metadata.csv"
    assert calls[1].kwargs["cos_filepath"] == "path/to/ineum_metadata.csv"
    assert_frame_equal(calls[0].kwargs["df_metadata"], df1)
    assert_frame_equal(calls[1].kwargs["df_metadata"], df2)
