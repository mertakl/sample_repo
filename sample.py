def process_document(
    self,
    document: SharepointDocument,
    failed_download_uids: set[str],
) -> str:
    cos_filepath = self.path_manager.get_document_path(
        uid=document.uid, source=document.source, language=document.language
    )

    document_status = self._download_document_status(
        cos_filepath=cos_filepath, document=document, failed_download_uids=failed_download_uids
    )
    logger.info("Document download status for %s is %s", document.uid, document_status)

    if document_status in [
        DownloadStatus.RECENTLY_MODIFIED,
        DownloadStatus.NEW_DOCUMENT,
        DownloadStatus.DOWNLOAD_FAILED_LAST_SUCCESSFUL_RUN,
    ] and not self._download_document_and_upload_to_cos(
        document=document, cos_filepath=cos_filepath
    ):
        logger.info("Download failed for %s. Skipping document.", document.uid)
        document_status = DownloadStatus.DOWNLOAD_FAILED

    self.download_status[document_status].append(document.uid)
    return document_status

def collect_metadata(
    self,
    document: SharepointDocument,
) -> tuple[Any, str]:
    """Returns (df_metadata, metadata_path) without saving to COS."""
    metadata_path = self.path_manager.get_source_metadata_path(source=document.source)
    df_metadata = self.metadata_manager.write_metadata(
        document=document, metadata_path=metadata_path
    )
    return df_metadata, metadata_path

def flush_metadata_to_cos(
    self,
    metadata_records: list[tuple[Any, str]],
) -> None:
    """Saves metadata to COS once per unique source path."""
    metadata_by_path: dict[str, Any] = {}
    for df_metadata, metadata_path in metadata_records:
        metadata_by_path[metadata_path] = df_metadata  # last write wins per source

    for metadata_path, df_metadata in metadata_by_path.items():
        self.metadata_manager.save_metadata_on_cos(
            df_metadata=df_metadata, cos_filepath=metadata_path
        )

# ...rest of the method
document_status_per_source_per_type = {source: defaultdict(list) for source in SOURCES}
metadata_records = []

for document in tqdm(all_documents, desc="Processing documents"):
    logger.info("Processing document %s in method process_document", document.name)
    status = self.doc_processor.process_document(
        document=document, failed_download_uids=failed_download_uids
    )
    # Collect metadata instead of saving per document
    if status != DownloadStatus.DOWNLOAD_FAILED:
        df_metadata, metadata_path = self.doc_processor.collect_metadata(document)
        metadata_records.append((df_metadata, metadata_path))

    document_status_per_source_per_type[document.source][status].append(document.uid)

# Single flush to COS after all documents processed
self.doc_processor.flush_metadata_to_cos(metadata_records)

document_status_per_source_per_type = {
    source: dict(status)
    for source, status in document_status_per_source_per_type.items()
}

# Write logs
self.doc_processor.write_log_files()

return deleted_uid_per_source, document_status_per_source_per_type
