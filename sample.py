# ---document_processor.py

class DocumentProcessor(BaseModel):
    """Processes SharePoint documents."""

    document_fetcher: IDocumentFetcherPort
    cos_api: StorageClientPort
    metadata_manager: MetadataManager
    path_manager: PathManager
    download_status: defaultdict[str, list[str]] = Field(
        default_factory=lambda: defaultdict(list)
    )  # status to list of uid
    logs_uid: str = "cos_update_logs.yaml"

    def write_log_files(self) -> None:
        """Overwrites log files."""
        with open(self.path_manager.sharepoint_path / self.logs_uid, "w") as file:
            yaml.safe_dump({status.value: self.download_status[status] for status in DownloadStatus}, file)

    def process_documents_batch(
        self,
        documents: list[SharepointDocument],
        failed_download_uids: set[str],
    ) -> dict[str, str]:
        """
        Processes all documents, batching COS uploads and metadata writes.
        Returns document status per document uid.
        """
        files_to_upload: list[tuple[bytes, str]] = []       # (content, cos_filepath)
        metadata_records: list[tuple[Any, str]] = []        # (document, metadata_path)
        document_statuses: dict[str, str] = {}

        for document in tqdm(documents, desc="Processing documents"):
            logger.info("Processing document %s", document.name)

            cos_filepath = self.path_manager.get_document_path(
                uid=document.uid, source=document.source, language=document.language
            )

            document_status = self._download_document_status(
                cos_filepath=cos_filepath,
                document=document,
                failed_download_uids=failed_download_uids,
            )
            logger.info("Document download status for %s is %s", document.uid, document_status)

            if document_status in [
                DownloadStatus.RECENTLY_MODIFIED,
                DownloadStatus.NEW_DOCUMENT,
                DownloadStatus.DOWNLOAD_FAILED_LAST_SUCCESSFUL_RUN,
            ]:
                # ---- Collect file content instead of uploading immediately ----
                file_content = self.document_fetcher.download_file(
                    server_relative_url=document.server_relative_url
                )
                if file_content is None:
                    logger.error("Error while downloading document %s", document.server_relative_url)
                    document_status = DownloadStatus.DOWNLOAD_FAILED
                else:
                    files_to_upload.append((file_content, cos_filepath))
                    metadata_records.append((document, cos_filepath))

            self.download_status[document_status].append(document.uid)
            document_statuses[document.uid] = document_status

        # ---- Single batch upload to COS ----
        logger.info("Uploading %d files to COS in batch", len(files_to_upload))
        for file_content, cos_filepath in files_to_upload:
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                temp_file.write(file_content)
                self.cos_api.upload_file(file_path=temp_file.name, key=cos_filepath)

        # ---- Single batch metadata write ----
        all_metadata = []
        for document, cos_filepath in metadata_records:
            metadata_path = self.path_manager.get_source_metadata_path(source=document.source)
            df_metadata = self.metadata_manager.write_metadata(
                document=document, metadata_path=metadata_path
            )
            all_metadata.append((df_metadata, metadata_path))

        # Save all metadata to COS once per source
        metadata_by_source: dict[str, Any] = {}
        for df_metadata, metadata_path in all_metadata:
            metadata_by_source[metadata_path] = df_metadata  # last write wins per path

        for metadata_path, df_metadata in metadata_by_source.items():
            self.metadata_manager.save_metadata_on_cos(
                df_metadata=df_metadata, cos_filepath=metadata_path
            )

        return document_statuses



