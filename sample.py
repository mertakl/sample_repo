# orchestrator.py
from concurrent.futures import ThreadPoolExecutor, as_completed

document_status_per_source_per_type = {source: defaultdict(list) for source in SOURCES}

# Phase 1: Determine download status for all documents (cheap, no network I/O)
documents_to_download = []
for document in tqdm(all_documents, desc="Checking document statuses"):
    status = self.doc_processor.get_document_status(
        document=document,
        failed_download_uids=failed_download_uids,
    )
    if status in STATUSES_REQUIRING_DOWNLOAD:
        documents_to_download.append(document)
    else:
        document_status_per_source_per_type[document.source][status].append(document.uid)

# Phase 2: Download + upload in parallel
with ThreadPoolExecutor(max_workers=10) as executor:
    future_to_doc = {
        executor.submit(self.doc_processor.download_and_upload, document): document
        for document in documents_to_download
    }
    for future in tqdm(as_completed(future_to_doc), total=len(future_to_doc), desc="Downloading documents"):
        document = future_to_doc[future]
        try:
            status = future.result()
        except Exception as e:
            logger.error("Unexpected error processing %s: %s", document.uid, e)
            status = DownloadStatus.DOWNLOAD_FAILED
        document_status_per_source_per_type[document.source][status].append(document.uid)

# Phase 3: Batch-write metadata once per source
self.doc_processor.flush_metadata()

document_status_per_source_per_type = {
    source: dict(status)
    for source, status in document_status_per_source_per_type.items()
}


# document_processor.py
import threading

class DocumentProcessor(BaseModel):
    """Processes SharePoint documents."""

    document_fetcher: IDocumentFetcherPort
    cos_api: StorageClientPort
    metadata_manager: MetadataManager
    path_manager: PathManager

    download_status: defaultdict[str, list[str]] = Field(
        default_factory=lambda: defaultdict(list)
    )
    logs_uid: str = "cos_update_logs.yaml"

    # Accumulated metadata rows, keyed by source; flushed in batch at the end
    _pending_documents: dict[str, list[SharepointDocument]] = Field(
        default_factory=dict
    )
    _lock: threading.Lock = Field(default_factory=threading.Lock)

    def get_document_status(
        self,
        document: SharepointDocument,
        failed_download_uids: set[str],
    ) -> str:
        """Determine download status without performing any download."""
        cos_filepath = self.path_manager.get_document_path(
            uid=document.uid,
            source=document.source,
            language=document.language,
        )
        return self._get_document_download_status(
            cos_filepath=cos_filepath,
            document=document,
            failed_download_uids=failed_download_uids,
        )

    def download_and_upload(self, document: SharepointDocument) -> str:
        """Download from SharePoint, upload to COS. Thread-safe."""
        cos_filepath = self.path_manager.get_document_path(
            uid=document.uid,
            source=document.source,
            language=document.language,
        )
        success = self._download_document_and_upload_to_cos(
            document=document,
            cos_filepath=cos_filepath,
        )
        if not success:
            logger.info("Download failed for %s. Skipping document.", document.uid)
            return DownloadStatus.DOWNLOAD_FAILED

        # Stage metadata for batch write; avoid concurrent list mutations
        with self._lock:
            self._pending_documents.setdefault(document.source, []).append(document)

        return DownloadStatus.DOWNLOADED  # fix: was implicitly returning None

    def flush_metadata(self) -> None:
        """Write all staged metadata to COS in one pass per source."""
        for source, documents in self._pending_documents.items():
            metadata_path = self.path_manager.get_source_metadata_path(source=source)
            df_metadata = self.metadata_manager.write_metadata_bulk(
                documents=documents,
                metadata_path=metadata_path,
            )
            self.metadata_manager.save_metadata_on_cos(
                df_metadata=df_metadata,
                cos_filepath=metadata_path,
            )
        self._pending_documents.clear()

    def _get_document_download_status(
        self,
        cos_filepath: str,
        document: SharepointDocument,
        failed_download_uids: set[str],
    ) -> str:
        """Determine download status based on prior failures, existence, and modification time."""
        if document.uid in failed_download_uids:
            return DownloadStatus.DOWNLOAD_FAILED_LAST_SUCCESSFUL_RUN

        if not self.cos_api.file_exists(file_path=cos_filepath):
            return DownloadStatus.NEW_DOCUMENT

        max_hours = get_max_hours_updated_document(
            last_success_filepath=self.path_manager.last_success_filepath()
        )
        if is_recently_modified(
            last_modified_str=document.time_last_modified,
            max_hours_updated_document=max_hours,
        ):
            return DownloadStatus.RECENTLY_MODIFIED

        return DownloadStatus.FILE_EXISTS_AND_NOT_MODIFIED

    def _download_document_and_upload_to_cos(
        self,
        document: SharepointDocument,
        cos_filepath: str,
    ) -> bool:
        """Downloads document from SharePoint and uploads it to COS."""
        logger.info("Downloading document %s from SharePoint.", document.uid)

        file_content = self.document_fetcher.download_file(
            server_relative_url=document.server_relative_url
        )
        if file_content is None:
            logger.error("Error while downloading document %s", document.server_relative_url)
            return False

        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(document.url).suffix) as temp_file:
            temp_file.write(file_content)
            logger.info("Uploading document %s to COS.", document.uid)
            self.cos_api.upload_file(file_path=temp_file.name, key=cos_filepath)

        return True  # metadata is now deferred to flush_metadata()


def write_metadata_bulk(
    self,
    documents: list[SharepointDocument],
    metadata_path: str,
) -> pd.DataFrame:
    """Write metadata for multiple documents at once, avoiding per-document I/O."""
    rows = [self._build_metadata_row(doc) for doc in documents]
    df_new = pd.DataFrame(rows)

    if self.cos_api.file_exists(metadata_path):
        df_existing = self.load_metadata_from_cos(metadata_path)
        df_combined = pd.concat([df_existing, df_new]).drop_duplicates(subset=["uid"], keep="last")
    else:
        df_combined = df_new

    return df_combined
