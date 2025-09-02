async def run(self, project_args) -> None:
        """Main execution method to run the entire synchronization process."""
        self._handle_deleted_files()

def get_deleted_file_names(self) -> list[str]:
        """Retrieves a list of deleted file names from the SharePoint recycle bin."""
        logger.info("Retrieving deleted file names from SharePoint recycle bin.")
        try:
            endpoint = "/_api/site/RecycleBin?$filter=ItemState eq 1"
            response = self.api_client.send_request(endpoint)
            deleted_items = response.get("d", {}).get("results", [])
            return [item.get("Title", "") for item in deleted_items if item.get("Title")]
        except (ConnectionError, KeyError) as e:
            logger.error("Failed to retrieve deleted files: %s", e)
            return []



def _handle_deleted_files(self) -> None:
        """Handle deletion of files that were removed from SharePoint."""
        deleted_files = self.sp_service.get_deleted_file_names()
        if deleted_files:
            for file_name in deleted_files:
                self.doc_processor.delete_document(file_name=file_name)
				
				
				
def delete_document(self, file_name: str) -> None:
        """Delete document from COS and update metadata."""
        metadata_path = self.path_manager.get_metadata_path()

        deleted_doc_metadata = self.metadata_manager.get_metadata_by_filename(
            file_name=file_name, metadata_path=metadata_path
        )

        if not deleted_doc_metadata:
            # Nothing to delete
            return

        # Delete file from COS
        source, language = deleted_doc_metadata["source"], deleted_doc_metadata["language"]
        file_path = self.path_manager.get_document_path(
            source=source, language=language, file_name=file_name
        )
        logger.info("Deleting file %s", file_name)
        self.cos_api.delete_file(str(file_path))

        # Remove from metadata
        self.metadata_manager.remove_metadata(metadata_path=metadata_path, file_name=file_name)
		
		
---------------
class MetadataManager:
    """Manages CSV metadata operations."""

    def __init__(self, cos_api: CosBucketApi):  # noqa: D107
        self.cos_api = cos_api

    def get_metadata_by_filename(self, file_name: str, metadata_path: str) -> dict[str, Any] | None:
        """Get metadata for specific file."""
        if not self.cos_api.file_exists(metadata_path):
            return None

        try:
            df = self.cos_api.read_csv(metadata_path, sep=";")
            filtered_df = df[df["file_name"] == file_name]
            return filtered_df.iloc[0].to_dict() if not filtered_df.empty else None
        except (pd.errors.EmptyDataError, KeyError, IndexError):
            return None
