import logging
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import Generator, List, Dict, Any

# Assuming these imports exist based on your snippet
# from your_module import Event, UpdatePublicationDocumentResult

logger = logging.getLogger(__name__)

@dataclass
class PublicationStats:
    """Helper class to track publication processing statistics."""
    count: int = 0
    processed: int = 0
    created: int = 0
    updated: int = 0
    no_update_needed: int = 0
    document_updated: int = 0
    cancelled: int = 0
    document_error: int = 0
    errors: List[str] = field(default_factory=list)

    def record_result(self, result: 'UpdatePublicationDocumentResult'):
        self.processed += 1
        
        # Mapping logic moved here to clean up the main loop
        if result == UpdatePublicationDocumentResult.OK_CREATED_SUCCESSFULLY:
            self.created += 1
        elif result == UpdatePublicationDocumentResult.OK_UPDATED_SUCCESSFULLY:
            self.updated += 1
        elif result == UpdatePublicationDocumentResult.OK_NO_NEED_TO_UPDATE:
            self.no_update_needed += 1
        elif result == UpdatePublicationDocumentResult.OK_DOCUMENT_UPDATED_SUCCESSFULLY:
            self.document_updated += 1
        elif result == UpdatePublicationDocumentResult.CANCELLED:
            self.cancelled += 1
        elif result.value.startswith("ERROR"):
            self.document_error += 1
            self.errors.append(result.value)
        else:
            logger.error("Internal Error: unknown update result %s", result)

    def to_dict(self, prefix: str = "") -> Dict[str, Any]:
        """Returns a dictionary suitable for logging extra data."""
        p = f"{prefix}_" if prefix else ""
        return {
            f"{p}publications_scanned": self.count,
            f"{p}publications_processed": self.processed,
            f"{p}publications_created": self.created,
            f"{p}publications_updated": self.updated,
            f"{p}publications_no_update_needed": self.no_update_needed,
            f"{p}documents_updated": self.document_updated,
            f"{p}publications_cancelled": self.cancelled,
            f"{p}publication_documents_errors": self.document_error,
            "errors": self.errors,
        }

    def generate_message(self, label: str) -> str:
        return (
            f"{label} {self.count} publications: "
            f"{self.processed} processed, "
            f"{self.created} created, "
            f"{self.updated} updated, "
            f"{self.no_update_needed} no update needed, "
            f"{self.document_updated} docs updated, "
            f"{self.cancelled} cancelled, "
            f"{self.document_error} errors."
        )

    def merge(self, other: 'PublicationStats'):
        """Accumulate batch stats into total stats."""
        self.count += other.count
        self.processed += other.processed
        self.created += other.created
        self.updated += other.updated
        self.no_update_needed += other.no_update_needed
        self.document_updated += other.document_updated
        self.cancelled += other.cancelled
        self.document_error += other.document_error
        self.errors.extend(other.errors)


class Heartbeat:
    """Manages the 'say hello' logic to keep the task executor alive."""
    def __init__(self, interval_seconds: int = 10):
        self.last_beat = datetime.now()
        self.interval = interval_seconds

    def should_beat(self) -> bool:
        if (datetime.now() - self.last_beat).total_seconds() > self.interval:
            self.last_beat = datetime.now()
            return True
        return False


class PublicationImporter: 
    # (Assuming this method belongs to a class like this)

    def _fetch_and_save_publications(
        self,
        *,
        from_publication_date,
        to_publication_date,
        publication_zipcode,
        vat,
        max_fetched_page_count,
        cancellation_event: Event,
        attempt: int = 0,
    ) -> Generator[str | None, None, None]:
        
        heartbeat = Heartbeat()
        total_stats = PublicationStats()
        attempt += 1

        try:
            # Main Processing Loop
            generator = self.processor.process(
                from_publication_date=from_publication_date,
                to_publication_date=to_publication_date,
                publication_zipcode=publication_zipcode,
                vat=vat,
                max_fetched_page_count=max_fetched_page_count,
                cancellation_event=cancellation_event,
            )

            for publication_batch in generator:
                if heartbeat.should_beat():
                    yield None

                if not publication_batch:
                    continue

                # Process individual batch
                batch_stats = self._process_batch(
                    publication_batch, 
                    heartbeat, 
                    cancellation_event
                )
                
                # Log and Yield Batch Results
                logger.info(
                    "Saving a batch of %s publications.", len(publication_batch)
                )
                
                # Yield heartbeats that occurred inside the batch processing
                # (Note: _process_batch cannot yield directly if called as a sub-function 
                # unless we yield from it, but passing the generator is cleaner)
                yield from self._yield_batch_heartbeats(batch_stats)
                
                total_stats.merge(batch_stats)
                
                msg = batch_stats.generate_message(f"Batch of {len(publication_batch)}")
                log_method = logger.error if batch_stats.document_error > 0 else logger.info
                log_method(msg, extra=batch_stats.to_dict(prefix="batch"))
                
                yield msg

            # Final Summary
            final_msg = total_stats.generate_message("TOTAL")
            log_method = logger.error if total_stats.document_error > 0 else logger.info
            log_method("Scan finished.", extra=total_stats.to_dict())
            yield final_msg

            # Retry Logic
            yield from self._handle_retries(
                from_publication_date, to_publication_date, publication_zipcode, vat,
                max_fetched_page_count, cancellation_event, attempt
            )

        except Exception as e:
            logger.error("Error saving publications: %s", str(e), exc_info=True)
            traceback.print_exc()
            raise

    def _process_batch(
        self, 
        batch: list, 
        heartbeat: Heartbeat, 
        cancellation_event: Event
    ) -> PublicationStats:
        """Processes a single batch of publications and returns stats."""
        stats = PublicationStats(count=len(batch))
        
        # We store needed heartbeats in a temporary list on the stats object 
        # or handle them via a generator. To keep it simple in a helper method:
        stats.heartbeats_needed = 0 

        results = self.document_service.batch_update_publication_documents_from_moniteur_belge(
            publications=batch,
            max_workers=self.max_workers_download,
            cancellation_event=cancellation_event,
        )

        for update_result in results:
            stats.record_result(update_result)
            if heartbeat.should_beat():
                stats.heartbeats_needed += 1
        
        return stats

    def _yield_batch_heartbeats(self, stats: PublicationStats) -> Generator[None, None, None]:
        """Yields the number of heartbeats accumulated during batch processing."""
        # This is a workaround because _process_batch is not a generator
        if hasattr(stats, 'heartbeats_needed'):
            for _ in range(stats.heartbeats_needed):
                yield None

    def _handle_retries(
        self,
        from_date, to_date, zipcode, vat, max_pages, event, attempt
    ) -> Generator[str | None, None, None]:
        """Checks for incomplete downloads and triggers recursion if needed."""
        num_incomplete = self._incomplete_publications(from_date, to_date, zipcode, vat)
        
        if num_incomplete > 0:
            if attempt <= self.max_retry_batch:
                logger.warning(
                    "%s incomplete publications, retry number %s", 
                    num_incomplete, attempt
                )
                yield from self._fetch_and_save_publications(
                    from_publication_date=from_date,
                    to_publication_date=to_date,
                    publication_zipcode=zipcode,
                    vat=vat,
                    max_fetched_page_count=max_pages,
                    cancellation_event=event,
                    attempt=attempt,
                )
            else:
                msg = (f"Max Retry Limit reached. Could not download files for "
                       f"{num_incomplete} publications")
                logger.error(msg)
                yield msg
