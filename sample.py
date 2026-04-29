def test_write_metadata_with_existing_df(metadata_manager, sso_document_metadata_only_ineuversal):
    """Test writing metadata when df_metadata is passed in — no COS read should occur."""
    existing_df = pd.DataFrame([{"uid": "old_doc", "source": "eureka"}])
    
    metadata = EurekaSharepointDocument(
        title="Test Title",
        author="Test Author",
        name="test.docx",
        server_relative_url="/test/test.docx",
        url="https://sharepoint.com/sites/test/test.docx",
        time_last_modified="2023-01-01T00:00:00Z",
        library="TestLibrary",
        subfolder="TestFolder",
        nota_number="123",
        language="FR",
        **sso_document_metadata_only_ineuversal,
    )

    with patch("bnppf_rag_engine.sharepoint.metadata_manager.read_csv") as read_csv_mock:
        df = metadata_manager.write_metadata(
            metadata, "test_path.csv", df_metadata=existing_df
        )

        # COS should never be touched when df_metadata is provided
        read_csv_mock.assert_not_called()
        metadata_manager.cos_api.file_exists.assert_not_called()

        # Old entry still present, new entry appended
        assert len(df) == 2
        assert "old_doc" in df["uid"].values
        assert "123@FR@docx@TestFolder" in df["uid"].values
