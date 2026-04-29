def write_metadata(
    self,
    document: SharepointDocument,
    metadata_path: str,
    df_metadata: pd.DataFrame | None = None,  # pass existing df to avoid COS read
) -> pd.DataFrame:
    """Write metadata to CSV file."""
    logger.info("Writing metadata information for %s", {document.uid})

    # Create new entry
    metadata = document.model_dump()
    metadata["uid"] = document.uid  # not in model_dump as it's a property
    new_entry = pd.DataFrame([metadata])

    # Load df_metadata only if not provided
    if df_metadata is None:
        if self.cos_api.file_exists(metadata_path):
            df_metadata = read_csv(metadata_path, sep=";", cos_client=self.cos_api)
        else:
            df_metadata = self._create_empty_dataframe(columns=metadata)

    # Delete entry (if exists)
    df_metadata = self.remove_metadata(df_metadata=df_metadata, uid=document.uid)

    return pd.concat([df_metadata, new_entry], ignore_index=True)


# In orchestrator.py - load existing metadata from COS once per source upfront
metadata_cache: dict[str, pd.DataFrame] = {}
metadata_records = []

for document in tqdm(all_documents, desc="Processing documents"):
    logger.info("Processing document %s in method process_document", document.name)
    status = self.doc_processor.process_document(
        document=document, failed_download_uids=failed_download_uids
    )

    if status != DownloadStatus.DOWNLOAD_FAILED:
        metadata_path = self.doc_processor.path_manager.get_source_metadata_path(
            source=document.source
        )
        # Load from COS once per source, reuse in-memory after
        if metadata_path not in metadata_cache:
            if self.doc_processor.cos_api.file_exists(metadata_path):
                metadata_cache[metadata_path] = read_csv(
                    metadata_path, sep=";", cos_client=self.doc_processor.cos_api
                )
            else:
                metadata_cache[metadata_path] = None  # will trigger empty df creation

        df_metadata = self.doc_processor.metadata_manager.write_metadata(
            document=document,
            metadata_path=metadata_path,
            df_metadata=metadata_cache[metadata_path],  # pass cached df
        )
        metadata_cache[metadata_path] = df_metadata  # update cache with new entry

    document_status_per_source_per_type[document.source][status].append(document.uid)

# Single flush to COS - one write per source
self.doc_processor.flush_metadata_to_cos(
    [(df, path) for path, df in metadata_cache.items() if df is not None]
)
