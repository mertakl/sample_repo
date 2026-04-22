# Constants to avoid repeated inline sets
STATUSES_REQUIRING_DOWNLOAD = frozenset({
    DownloadStatus.RECENTLY_MODIFIED,
    DownloadStatus.NEW_DOCUMENT,
    DownloadStatus.DOWNLOAD_FAILED_LAST_SUCCESSFUL_RUN,
})


def process_document(
    self,
    document: SharepointDocument,
    failed_download_uids: set[str],
) -> str:
    cos_filepath = self.path_manager.get_document_path(
        uid=document.uid,
        source=document.source,
        language=document.language,
    )

    document_status = self._download_document_status(
        cos_filepath=cos_filepath,
        document=document,
        failed_download_uids=failed_download_uids,
    )
    logger.info("Document download status for %s is %s", document.uid, document_status)

    if document_status in STATUSES_REQUIRING_DOWNLOAD:
        document_status = self._attempt_download(document, cos_filepath)

    self.download_status[document_status].append(document.uid)
    return document_status


def _attempt_download(
    self,
    document: SharepointDocument,
    cos_filepath: str,
) -> str:
    """Try to download document; return updated status."""
    success = self._download_document_and_upload_to_cos(
        document=document,
        cos_filepath=cos_filepath,
    )
    if not success:
        logger.info("Download failed for %s. Skipping document.", document.uid)
        return DownloadStatus.DOWNLOAD_FAILED
    return DownloadStatus.DOWNLOAD_SUCCESS


def _download_document_status(
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
