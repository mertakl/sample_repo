def process_document(self, doc: ProcessedDocument, parsed_args) -> tuple[bool, bytes | None]:
    """Process a single document. Returns (was_uploaded, file_content)."""
    file_info = doc.file
    file_name = file_info["Name"]
    last_modified = file_info["TimeLastModified"]
    
    file_path = self.path_manager.get_document_path(
        source=doc.source, 
        language=doc.language, 
        file_name=file_name
    )

    # Skip non-parseable files
    if not DocumentFilter.is_parseable(file_name):
        self._log_unparseable_document(file_name, doc, parsed_args)
        return False, None

    # Check if upload is needed
    needs_upload = self._should_upload_document(file_path, last_modified)
    
    if needs_upload:
        file_content = self._upload_document(doc, file_path)
        return True, file_content
    
    return False, None

def _should_upload_document(self, file_path: str, last_modified) -> bool:
    """Determine if document should be uploaded based on modification time and existence."""
    if DocumentFilter.is_recently_modified(last_modified):
        return True
    
    # Only upload old files if they don't exist in storage
    return not self.cos_api.file_exists(file_path)
