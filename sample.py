def update_publication_document_from_moniteur_belge(
    self,
    publication: LegalEntityPublication,
    cancellation_event: Event | None = None,
) -> UpdatePublicationResult:
    """
    Updates or creates a publication document from Moniteur Belge.
    
    Handles four cases:
    1. New publication - create and download
    2. Identical existing publication - skip
    3. Existing without document - update and download
    4. Existing with different metadata - update metadata only
    """
    
    def log_pub(msg: str, level: str = "debug") -> None:
        """Helper to log publication-specific messages."""
        getattr(logger, level)(
            msg,
            publication.legal_entity_vat,
            publication.publication_number,
            publication.publication_date,
        )
    
    # Early exit conditions
    if cancellation_event and cancellation_event.is_set():
        log_pub(
            "Cancelled update for publication VAT: %s, NUMBER: %s, DATE: %s"
        )
        return UpdatePublicationResult.CANCELLED
    
    if publication.publication_document_id is None:
        return UpdatePublicationResult.IGNORED
    
    try:
        log_pub("Searching for publication %s, %s, %s")
        
        existing = self._get_existing_publication(publication)
        
        if existing is None:
            return self._handle_new_publication(publication, log_pub)
        
        if self._publications_are_identical(existing, publication):
            log_pub("Publication VAT: %s, DATE: %s already exists")
            return UpdatePublicationResult.OK_NO_NEED_TO_UPDATE
        
        if not existing.publication_document_id:
            return self._handle_missing_document(publication, log_pub)
        
        return self._handle_metadata_update(publication, log_pub)
    
    except Exception as e:
        logger.error(
            "Error saving publication VAT: %s, DATE: %s. Error: %s",
            publication.legal_entity_vat,
            publication.publication_date,
            str(e),
            exc_info=True,
        )
        return UpdatePublicationResult.ERROR_OTHER
    
    finally:
        connection.close()
    
    # Helper methods
    
    def _get_existing_publication(
        self, publication: LegalEntityPublication
    ) -> LegalEntityPublication | None:
        """Retrieve existing publication matching the given criteria."""
        return LegalEntityPublication.objects.filter(
            legal_entity_vat=publication.legal_entity_vat,
            publication_number=publication.publication_number,
            publication_date=publication.publication_date,
        ).first()
    
    def _publications_are_identical(
        self, existing: LegalEntityPublication, new: LegalEntityPublication
    ) -> bool:
        """Check if two publications are identical."""
        return existing == new
    
    def _handle_new_publication(
        self, publication: LegalEntityPublication, log_pub
    ) -> UpdatePublicationResult:
        """Handle creation of a new publication."""
        log_pub(
            "Publication VAT: %s, NUMBER: %s, DATE: %s does not exist. "
            "Creating and downloading document..."
        )
        
        if not self._download_n_save_document(publication):
            publication.publication_document_id = None
            return UpdatePublicationResult.ERROR_METADATA_CREATED_BUT_DOCUMENT_FAILED
        
        publication.save(force_insert=True)
        return UpdatePublicationResult.OK_CREATED_SUCCESSFULLY
    
    def _handle_missing_document(
        self, publication: LegalEntityPublication, log_pub
    ) -> UpdatePublicationResult:
        """Handle publication that exists but has no document."""
        log_pub(
            "Publication VAT: %s, NUMBER: %s, DATE: %s exists but missing document. "
            "Updating and downloading..."
        )
        logger.info(
            "File %s was previously missing — retrying download",
            publication.document_url,
        )
        
        if not self._download_n_save_document(publication):
            return UpdatePublicationResult.ERROR_UPDATE_DOCUMENT_FAILED
        
        publication.save(force_update=True)
        return UpdatePublicationResult.OK_DOCUMENT_UPDATED_SUCCESSFULLY
    
    def _handle_metadata_update(
        self, publication: LegalEntityPublication, log_pub
    ) -> UpdatePublicationResult:
        """Handle publication with different metadata."""
        log_pub(
            "Publication VAT: %s, NUMBER: %s, DATE: %s exists with different metadata. "
            "Updating...",
            level="info"
        )
        publication.save(force_update=True)
        return UpdatePublicationResult.OK_UPDATED_SUCCESSFULLY
