df_metadata = read_csv(key=metadata_path, sep=";", cos_client=self.cos_api)

# Guard: if metadata is empty or has no uid column, nothing to filter
if df_metadata.empty or "uid" not in df_metadata.columns:
    df_to_csv(
        df=df_metadata,
        cos_filename=metadata_path,
        header=True,
        cos_client=self.cos_api,
    )
    return deleted_uids

df_metadata = df_metadata[~df_metadata["uid"].isin(deleted_uids_set)]


existing_metadata = pd.DataFrame([
    {
        "uid": deleted_cos_search.uid,
        "language": "EN",
        "source": "eureka",
    }
])

with patch(
    "bnppf_rag_engine.sharepoint.document_processor.read_csv",
    return_value=existing_metadata,  # ← has uid column
):
    document_processor.manage_deleted_documents(existing_doc)
