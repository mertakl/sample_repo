def update_publication_document_from_moniteur_belge(
    self, 
    publication: LegalEntityPublication, 
    cancellation_event: Event | None = None
) -> UpdatePublicationResult:
    """
    Update publication document from Moniteur Belge.
    
    Returns appropriate UpdatePublicationResult based on the operation outcome.
    """
    # Handle cancellation
    if cancellation_event and cancellation_event.is_set():
        logger.debug(
            "Cancelled update_publication_document_from_moniteur_belge for publication with "
            "VAT: %s, NUMBER: %s, DATE: %s",
            publication.legal_entity_vat,
            publication.publication_number,
            publication.publication_date,
        )
        return UpdatePublicationResult.CANCELLED
    
    try:
        logger.debug(
            "Searching for publication %s, %s, %s",
            publication.legal_entity_vat,
            publication.publication_number,
            publication.publication_date,
        )
        
        # Check if document already exists
        if publication.publication_document_id is None:
            result = self._handle_new_publication(publication)
        else:
            result = self._handle_existing_publication(publication)
            
        return result
        
    except Exception as e:
        logger.error(
            "Error saving publication with VAT: %s and DATE: %s. Stack Trace: %s",
            publication.legal_entity_vat,
            publication.publication_date,
            str(e),
            exc_info=True,
        )
        traceback.print_exc()
        return UpdatePublicationResult.ERROR_OTHER
        
    finally:
        connection.close()


def _handle_new_publication(self, publication: LegalEntityPublication) -> UpdatePublicationResult:
    """Handle publication that doesn't exist in DB yet."""
    existing_publication = LegalEntityPublication.objects.filter(
        legal_entity_vat=publication.legal_entity_vat,
        publication_number=publication.publication_number,
        publication_date=publication.publication_date,
    ).first()
    
    if not existing_publication:
        logger.debug(
            "Publication with VAT: %s, NUMBER: %s, DATE: %s does not exists yet. "
            "Inserting the entry in the DB and downloading the document...",
            publication.legal_entity_vat,
            publication.publication_number,
            publication.publication_date,
        )
        
        successfully_saved_file = self._download_n_save_document(publication)
        
        if not successfully_saved_file:
            publication.publication_document_id = None
            return UpdatePublicationResult.ERROR_METADATA_CREATED_BUT_DOCUMENT_FAILED
        
        publication.save(force_insert=True)
        return UpdatePublicationResult.OK_CREATED_SUCCESSFULLY
    
    # Publication exists but without document
    logger.debug(
        "Publication with VAT: %s and DATE: %s already exists",
        publication.legal_entity_vat,
        publication.publication_date,
    )
    return UpdatePublicationResult.OK_NO_NEED_TO_UPDATE


def _handle_existing_publication(self, publication: LegalEntityPublication) -> UpdatePublicationResult:
    """Handle publication that already has a document."""
    logger.info(
        "Publication with VAT: %s, NUMBER: %s, and DATE: %s already exists but without a document. "
        "Updating Metadata and document",
        publication.legal_entity_vat,
        publication.publication_number,
        publication.publication_date,
    )
    
    successfully_saved_file = self._download_n_save_document(publication)
    
    if not successfully_saved_file:
        return UpdatePublicationResult.ERROR_UPDATE_DOCUMENT_FAILED
    
    publication.publication_document_id = publication.publication_document_id
    publication.save(force_update=True)
    
    logger.info(
        "Publication with VAT: %s, NUMBER: %s, and DATE: %s already exists but some fields are not the same. "
        "Updating Metadata",
        publication.legal_entity_vat,
        publication.publication_number,
        publication.publication_date,
    )
    publication.save(force_update=True)
    
    return UpdatePublicationResult.OK_UPDATED_SUCCESSFULLY
