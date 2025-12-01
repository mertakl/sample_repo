def say_hello() -> bool:
    nonlocal latest_hello
    if (datetime.now() - latest_hello).total_seconds() > 10:
        latest_hello = datetime.now()
        return True
    return False

try:
    attempt += 1
    total_publication_count = 0
    total_publication_processed = 0
    total_publication_created = 0
    total_publication_updated = 0
    total_publication_no_update_needed = 0
    total_publication_document_updated = 0
    total_publication_cancelled = 0
    total_publication_document_error = 0
    errors = []
    
    for publication_batch in self.processor.process(
        from_publication_date=from_publication_date,
        to_publication_date=to_publication_date,
        publication_zipcode=publication_zipcode,
        vat=vat,
        max_fetched_page_count=max_fetched_page_count,
        cancellation_event=cancellation_event,
    ):
        if say_hello():
            yield None
        
        batch_publication_count = len(publication_batch)
        if batch_publication_count == 0:
            continue
        
        total_publication_count += batch_publication_count
        batch_publication_created = 0
        batch_publication_updated = 0
        batch_publication_no_update_needed = 0
        batch_publication_document_updated = 0
        batch_publication_cancelled = 0
        batch_publication_document_error = 0
        batch_publication_processed = 0
        
        logger.info("Saving a batch of %s publications.", batch_publication_count)
        for update_result in self.document_service.batch_update_publication_documents_from_moniteur_belge(
            publications=publication_batch,
            max_workers=self.max_workers_download,
            cancellation_event=cancellation_event,
        ):
            batch_publication_processed += 1
            total_publication_processed += 1
            
            if update_result == UpdatePublicationDocumentResult.OK_CREATED_SUCCESSFULLY:
                batch_publication_created += 1
                total_publication_created += 1
            elif update_result == UpdatePublicationDocumentResult.OK_UPDATED_SUCCESSFULLY:
                batch_publication_updated += 1
                total_publication_updated += 1
            elif update_result == UpdatePublicationDocumentResult.OK_NO_NEED_TO_UPDATE:
                batch_publication_no_update_needed += 1
                total_publication_no_update_needed += 1
            elif update_result == UpdatePublicationDocumentResult.OK_DOCUMENT_UPDATED_SUCCESSFULLY:
                batch_publication_document_updated += 1
                total_publication_document_updated += 1
            elif update_result == UpdatePublicationDocumentResult.CANCELLED:
                batch_publication_cancelled += 1
                total_publication_cancelled += 1
            elif update_result.value.startswith("ERROR"):
                batch_publication_document_error += 1
                total_publication_document_error += 1
                errors.append(update_result.value)
            else:
                logger.error("Internal Error : unknown update publication document result %s", update_result)
            
            if say_hello():
                yield None
        
        message = (
            f"Batch of {batch_publication_count} publications: "
            f"{batch_publication_processed} processed, "
            f"{batch_publication_created} created, "
            f"{batch_publication_updated} updated, " # New metric
            f"{batch_publication_no_update_needed} with no update needed, "
            f"{batch_publication_document_updated} documents updated, "
            f"{batch_publication_cancelled} cancelled, "
            f"{batch_publication_document_error} errors."
        )
        
        data = {
            "batch_publications_scanned": batch_publication_count,
            "batch_publications_processed": batch_publication_processed,
            "batch_publications_created": batch_publication_created,
            "batch_publications_updated": batch_publication_updated,
            "batch_publications_no_update_needed": batch_publication_no_update_needed,
            "batch_documents_updated": batch_publication_document_updated,
            "batch_publications_cancelled": batch_publication_cancelled,
            "batch_publication_documents_errors": batch_publication_document_error,
            "errors": errors,
        }
        
        if batch_publication_document_error > 0:
            logger.error(message, extra=data)
        else:
            logger.info(message, extra=data)
        yield message
    
    message = (
        f"TOTAL {total_publication_count} publications identified, "
        f"{total_publication_processed} processed, "
        f"{total_publication_created} created, "
        f"{total_publication_updated} updated, "
        f"{total_publication_no_update_needed} with no update needed, "
        f"{total_publication_document_updated} documents updated, "
        f"{total_publication_cancelled} cancelled, "
        f"{total_publication_document_error} with errors."
    )
    
    data = {
        "publications_scanned": total_publication_count,
        "publications_processed": total_publication_processed,
        "publications_created": total_publication_created,
        "publications_updated": total_publication_updated,
        "publications_no_update_needed": total_publication_no_update_needed,
        "documents_updated": total_publication_document_updated,
        "publications_cancelled": total_publication_cancelled,
        "publication_documents_errors": total_publication_document_error,
        "errors": errors,
    }
    
    if total_publication_document_error > 0:
        logger.error("Scan finished with errors.", extra=data)
    else:
        logger.info("Scan finished.", extra=data)
    yield message
    
    num_incomplete_publications = self._incomplete_publications(
        from_publication_date, to_publication_date, publication_zipcode, vat
    )
    
    if num_incomplete_publications > 0 and attempt <= self.max_retry_batch:
        logger.warning("%s incomplete publications, retry number %s", num_incomplete_publications, attempt)
        yield from self._fetch_and_save_publications(
            from_publication_date=from_publication_date,
            to_publication_date=to_publication_date,
            publication_zipcode=publication_zipcode,
            vat=vat,
            max_fetched_page_count=max_fetched_page_count,
            cancellation_event=cancellation_event,
            attempt=attempt,
        )
    
    if num_incomplete_publications > 0 and attempt > self.max_retry_batch:
        message = f"""Max Retry Limit has been reached,
