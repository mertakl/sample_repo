In the following process;


def _process_documents_for_source(self, lang: str, source: str, doc_list: list, project_args) -> list:
        """Process documents for a specific source and return newly uploaded ones."""
        newly_uploaded = []

        for doc_data in doc_list:
            processed_doc = ProcessedDocument(
                file=doc_data["File"],
                nota_number=doc_data.get("NotaNumber"),
                source=source,
                language=lang,
            )

            was_uploaded, file_content = self.doc_processor.process_document(
                doc=processed_doc, parsed_args=project_args
            )

            if was_uploaded:
                processed_doc.content = file_content
                newly_uploaded.append(processed_doc)

        return newly_uploaded

--------------------


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

        file_path = self.path_manager.get_document_path(source=source, language=language, file_name=file_name)

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
        file_path = self.path_manager.get_document_path(source=source, language=language, file_name=file_name)
        logger.info("Deleting file %s", file_name)
        self.cos_api.delete_file(str(file_path))

        # Remove from metadata
        self.metadata_manager.remove_metadata(metadata_path=metadata_path, file_name=file_name)

    def _upload_document_to_cos_and_save_metadata(self, doc: ProcessedDocument, document_path: str) -> bytes:
        """Upload document to COS and save metadata."""
        file_info = doc.file
        file_name, server_relative_url = file_info["Name"], file_info["ServerRelativeUrl"]

        logger.info("Downloading document %s from sharepoint...", file_name)

        # Download file content
        file_content = self.api_client.download_file(server_relative_url)

        # Create temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_name)[1]) as temp_file:
            temp_file.write(file_content)
            temp_file_path = temp_file.name

        try:
            logger.info("Uploading document %s to COS...", file_name)
            # Upload to COS
            self.cos_api.upload_file(temp_file_path, document_path)

            # Save metadata
            metadata = DocumentMetadata(
                file_name=file_name,
                url=server_relative_url,
                created_by=file_info.get("Author"),
                last_modified=file_info["TimeLastModified"],
                nota_number=doc.nota_number,
                language=doc.language,
                source=doc.source,
            )

            metadata_path = self.path_manager.get_metadata_path()
            self.metadata_manager.write_metadata(metadata, metadata_path)

            return file_content

        finally:
            # Clean up temporary file
            os.unlink(temp_file_path)

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
		
	
	
-------------

class DocumentFilter:
    """Handles document filtering logic."""

    PARSEABLE_EXTENSIONS = {".doc", ".docx", ".pdf"}  # noqa: RUF012

    @staticmethod
    def is_parseable(file_name: str) -> bool:
        """Check if document is parseable."""
        _, extension = os.path.splitext(file_name)
        return extension.lower() in DocumentFilter.PARSEABLE_EXTENSIONS
		
-----------

##I want the ".doc" documents to be converted to docx format.

##Here is the code that converts it.


def convert_doc_to_docx_locally(filepath: str | Path, path_to_docx: str | Path) -> None:
    """Converts a file or a folder of .doc to .docx format.

    Args:
        filepath: path to a single .doc or to a folder with one or several .doc (without *.doc)
        path_to_docx: path to a folder where the .docx will be written
    """
    subprocess.run(["lowriter", "--convert-to", "docx", f"{filepath}", "--outdir", f"{path_to_docx}"], check=False)
	
	
##Can you help?
