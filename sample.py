import os
import tempfile
import subprocess
from pathlib import Path


class DocumentProcessor:
    """Processes SharePoint documents."""

    def __init__(  # noqa: D107
        self, api_client: SharePointAPIClient, cos_api: CosBucketApi, metadata_manager: MetadataManager
    ):
        self.api_client = api_client
        self.cos_api = cos_api
        self.metadata_manager = metadata_manager
        self.path_manager = PathManager()

    def process_document(self, doc: ProcessedDocument, parsed_args) -> tuple[bool, bytes]:
        """Process a single document. Returns True if document was uploaded/updated."""
        file_info = doc.file
        file_name, last_modified, source, language = (
            file_info["Name"],
            file_info["TimeLastModified"],
            doc.source,
            doc.language,
        )

        # For .doc files, we'll convert and store them as .docx
        final_file_name = self._get_storage_filename(file_name)
        file_path = self.path_manager.get_document_path(
            source=source, language=language, file_name=final_file_name
        )

        if not DocumentFilter.is_parseable(file_name):
            self._log_unparseable_document(file_name, doc, parsed_args)
            return False, None

        if not DocumentFilter.is_recently_modified(last_modified):
            if not self.cos_api.file_exists(file_path):
                # File does not exist, upload it
                file_content = self._upload_document_to_cos_and_save_metadata(doc, file_path)
                return True, file_content
            return False, None  # File exists and not recently modified

        # File was recently modified, upload it
        file_content = self._upload_document_to_cos_and_save_metadata(doc, file_path)
        return True, file_content

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

    def _upload_document_to_cos_and_save_metadata(self, doc: ProcessedDocument, document_path: str) -> bytes:
        """Upload document to COS and save metadata."""
        file_info = doc.file
        file_name, server_relative_url = file_info["Name"], file_info["ServerRelativeUrl"]
        
        # Convert .doc filename to .docx for everything
        final_file_name = self._get_storage_filename(file_name)

        logger.info("Downloading document %s from sharepoint...", file_name)

        # Download file content
        file_content = self.api_client.download_file(server_relative_url)

        # Create temporary file with original extension
        original_extension = os.path.splitext(file_name)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=original_extension) as temp_file:
            temp_file.write(file_content)
            original_temp_path = temp_file.name

        try:
            # Handle .doc conversion
            if original_extension.lower() == '.doc':
                upload_file_path, final_file_content = self._convert_doc_to_docx(original_temp_path, file_name)
            else:
                upload_file_path = original_temp_path
                final_file_content = file_content

            logger.info("Uploading document %s to COS...", final_file_name)
            # Upload to COS
            self.cos_api.upload_file(upload_file_path, document_path)

            # Save metadata with converted filename
            metadata = DocumentMetadata(
                file_name=final_file_name,  # Converted filename
                url=server_relative_url,
                created_by=file_info.get("Author"),
                last_modified=file_info["TimeLastModified"],
                nota_number=doc.nota_number,
                language=doc.language,
                source=doc.source,
            )

            metadata_path = self.path_manager.get_metadata_path()
            self.metadata_manager.write_metadata(metadata, metadata_path)

            return final_file_content

        finally:
            # Clean up temporary files
            if os.path.exists(original_temp_path):
                os.unlink(original_temp_path)
            
            # Clean up converted file if it's different from original
            if original_extension.lower() == '.doc':
                converted_path = self._get_converted_docx_path(original_temp_path)
                if os.path.exists(converted_path):
                    os.unlink(converted_path)

    def _convert_doc_to_docx(self, doc_file_path: str, original_filename: str) -> tuple[str, bytes]:
        """Convert .doc file to .docx and return path to converted file and its content."""
        temp_dir = os.path.dirname(doc_file_path)
        
        # Convert .doc to .docx
        self.convert_doc_to_docx_locally(doc_file_path, temp_dir)
        
        # Get the converted file path
        converted_path = self._get_converted_docx_path(doc_file_path)
        
        if not os.path.exists(converted_path):
            raise FileNotFoundError(f"Conversion failed: {converted_path} not found after conversion")
        
        # Read the converted file content
        with open(converted_path, 'rb') as f:
            converted_content = f.read()
        
        logger.info("Successfully converted %s to .docx format", original_filename)
        return converted_path, converted_content

    def _get_converted_docx_path(self, doc_path: str) -> str:
        """Get the expected path of the converted .docx file."""
        base_path = os.path.splitext(doc_path)[0]
        return f"{base_path}.docx"

    def _get_storage_filename(self, original_filename: str) -> str:
        """Get the filename that will be used for storage (convert .doc to .docx)."""
        name, extension = os.path.splitext(original_filename)
        if extension.lower() == '.doc':
            return f"{name}.docx"
        return original_filename

    @staticmethod
    def convert_doc_to_docx_locally(filepath: str | Path, path_to_docx: str | Path) -> None:
        """Converts a file or a folder of .doc to .docx format.

        Args:
            filepath: path to a single .doc or to a folder with one or several .doc (without *.doc)
            path_to_docx: path to a folder where the .docx will be written
        """
        subprocess.run(
            ["lowriter", "--convert-to", "docx", f"{filepath}", "--outdir", f"{path_to_docx}"], 
            check=False
        )

    def _log_unparseable_document(self, file_name: str, doc: ProcessedDocument, p_args) -> None:
        """Log unparseable document."""
        DocumentParser.write_unparsed_docs(
            unparsable_docs=[file_name],
            source=doc.source,
            language=doc.language,
            project_name=p_args.project_name,
        )

        _, extension = os.path.splitext(file_name)
        logger.error("Files with extension '%s' are not supported", extension)
