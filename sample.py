def _manage_deleted_documents_per_source(
    self,
    documents: list[SharepointDocument],
    source: str,
) -> list[str]:
    """Detects SharePoint-deleted documents for one source, and deletes them in COS.

    Also updates metadata file for given source.
    """
    all_doc_uids = {doc.uid for doc in documents}

    # Collect all deleted uids in one pass
    deleted_uids = [
        cos_search.uid
        for cos_search in self._get_cos_documents_information(source=source)
        if cos_search.uid not in all_doc_uids
    ]

    # Early exit — skip COS read/write entirely if nothing to delete
    if not deleted_uids:
        return deleted_uids

    deleted_uids_set = set(deleted_uids)

    # Delete documents from COS
    for cos_search in self._get_cos_documents_information(source=source):
        if cos_search.uid in deleted_uids_set:
            logger.debug("Deleting %s with its metadata", cos_search)
            self.delete_document(cos_search=cos_search)

    # Load metadata once, filter all deleted uids in a single pass
    metadata_path = self.path_manager.get_source_metadata_path(source=source)
    df_metadata = read_csv(key=metadata_path, sep=";", cos_client=self.cos_api)
    df_metadata = df_metadata[~df_metadata["uid"].isin(deleted_uids_set)]

    # Save back metadata file once
    df_to_csv(
        df=df_metadata,
        cos_filename=metadata_path,
        header=True,
        cos_client=self.cos_api,
    )

    return deleted_uids
