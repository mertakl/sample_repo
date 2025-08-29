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
                file_content = self._upload_document(doc, file_path)
                return True, file_content
            return False, None  # File exists and not recently modified

        # File was recently modified, upload it
        file_content = self._upload_document(doc, file_path)
        return True, file_content
