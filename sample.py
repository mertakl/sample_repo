def update_publication_document_from_moniteur_belge(
    self,
    publication: LegalEntityPublication,
    cancellation_event: Event | None = None,
) -> UpdatePublicationResult:
    """
    Update or create a publication document from Moniteur Belge.
    
    Args:
        publication: The publication to update or create
        cancellation_event: Optional event to cancel the operation
        
    Returns:
        UpdatePublicationResult indicating the outcome of the operation
    """
    if self._is_cancelled(cancellation_event, publication):
        return UpdatePublicationResult.CANCELLED

    if not publication.publication_document_id:
        return UpdatePublicationResult.IGNORED

    try:
        result = self._process_publication(publication)
    except Exception as e:
        result = self._handle_error(publication, e)
    finally:
        connection.close()

    return result


def _is_cancelled(
    self, 
    cancellation_event: Event | None, 
    publication: LegalEntityPublication
) -> bool:
    """Check if the operation has been cancelled."""
    if cancellation_event and cancellation_event.is_set():
        logger.debug(
            "Cancelled update for publication (VAT: %s, NUMBER: %s, DATE: %s)",
            publication.legal_entity_vat,
            publication.publication_number,
            publication.publication_date,
        )
        return True
    return False


def _process_publication(
    self, 
    publication: LegalEntityPublication
) -> UpdatePublicationResult:
    """Process the publication based on whether it exists or not."""
    logger.debug(
        "Processing publication (VAT: %s, NUMBER: %s, DATE: %s)",
        publication.legal_entity_vat,
        publication.publication_number,
        publication.publication_date,
    )

    existing_publication = self._get_existing_publication(publication)

    if not existing_publication:
        return self._create_new_publication(publication)
    
    if self._publications_are_identical(existing_publication, publication):
        return self._handle_identical_publication(publication)
    
    if not existing_publication.publication_document_id:
        return self._update_missing_document(publication)
    
    return self._update_metadata(publication)


def _get_existing_publication(
    self, 
    publication: LegalEntityPublication
) -> LegalEntityPublication | None:
    """Retrieve existing publication from database."""
    return LegalEntityPublication.objects.filter(
        legal_entity_vat=publication.legal_entity_vat,
        publication_number=publication.publication_number,
        publication_date=publication.publication_date,
    ).first()


def _publications_are_identical(
    self,
    existing: LegalEntityPublication,
    new: LegalEntityPublication
) -> bool:
    """Check if two publications are identical."""
    return existing == new


def _create_new_publication(
    self, 
    publication: LegalEntityPublication
) -> UpdatePublicationResult:
    """Create a new publication entry and download its document."""
    logger.debug(
        "Creating new publication (VAT: %s, NUMBER: %s, DATE: %s)",
        publication.legal_entity_vat,
        publication.publication_number,
        publication.publication_date,
    )

    successfully_saved = self._download_n_save_document(publication)

    if not successfully_saved:
        publication.publication_document_id = None
        return UpdatePublicationResult.ERROR_METADATA_CREATED_BUT_DOCUMENT_FAILED
    
    publication.save(force_insert=True)
    return UpdatePublicationResult.OK_CREATED_SUCCESSFULLY


def _handle_identical_publication(
    self, 
    publication: LegalEntityPublication
) -> UpdatePublicationResult:
    """Handle case where publication already exists and is identical."""
    logger.debug(
        "Publication already exists and is up-to-date (VAT: %s, DATE: %s)",
        publication.legal_entity_vat,
        publication.publication_date,
    )
    return UpdatePublicationResult.OK_NO_NEED_TO_UPDATE


def _update_missing_document(
    self, 
    publication: LegalEntityPublication
) -> UpdatePublicationResult:
    """Update publication that exists but is missing its document."""
    logger.debug(
        "Updating publication with missing document (VAT: %s, NUMBER: %s, DATE: %s)",
        publication.legal_entity_vat,
        publication.publication_number,
        publication.publication_date,
    )
    
    logger.info(
        "Retrying download for previously missing file: %s",
        publication.document_url,
    )

    successfully_saved = self._download_n_save_document(publication)

    if not successfully_saved:
        return UpdatePublicationResult.ERROR_UPDATE_DOCUMENT_FAILED
    
    publication.save(force_update=True)
    return UpdatePublicationResult.OK_DOCUMENT_UPDATED_SUCCESSFULLY


def _update_metadata(
    self, 
    publication: LegalEntityPublication
) -> UpdatePublicationResult:
    """Update metadata for existing publication with different fields."""
    logger.info(
        "Updating metadata for publication (VAT: %s, NUMBER: %s, DATE: %s)",
        publication.legal_entity_vat,
        publication.publication_number,
        publication.publication_date,
    )

    publication.save(force_update=True)
    return UpdatePublicationResult.OK_UPDATED_SUCCESSFULLY


def _handle_error(
    self, 
    publication: LegalEntityPublication, 
    error: Exception
) -> UpdatePublicationResult:
    """Handle and log errors that occur during publication processing."""
    logger.error(
        "Error processing publication (VAT: %s, DATE: %s): %s",
        publication.legal_entity_vat,
        publication.publication_date,
        str(error),
        exc_info=True,
    )
    return UpdatePublicationResult.ERROR_OTHER
