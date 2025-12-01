from dataclasses import dataclass
from datetime import datetime
from threading import Event
from typing import Generator
import logging
import traceback

logger = logging.getLogger(__name__)


@dataclass
class PublicationStats:
    """Tracks publication processing statistics."""
    count: int = 0
    processed: int = 0
    created: int = 0
    updated: int = 0
    no_update_needed: int = 0
    document_updated: int = 0
    cancelled: int = 0
    document_error: int = 0
    errors: list = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    def to_dict(self, prefix: str = "") -> dict:
        """Convert stats to dictionary with optional prefix."""
        return {
            f"{prefix}scanned": self.count,
            f"{prefix}processed": self.processed,
            f"{prefix}created": self.created,
            f"{prefix}updated": self.updated,
            f"{prefix}no_update_needed": self.no_update_needed,
            f"{prefix}documents_updated": self.document_updated,
            f"{prefix}cancelled": self.cancelled,
            f"{prefix}document_errors": self.document_error,
            "errors": self.errors,
        }

    def format_message(self, label: str) -> str:
        """Format statistics as a human-readable message."""
        return (
            f"{label} {self.count} publications identified, "
            f"{self.processed} processed, "
            f"{self.created} created, "
            f"{self.updated} updated, "
            f"{self.no_update_needed} with no update needed, "
            f"{self.document_updated} documents updated, "
            f"{self.cancelled} cancelled, "
            f"{self.document_error} with errors."
        )

    def add_batch(self, batch_stats: 'PublicationStats'):
        """Add batch statistics to total."""
        self.count += batch_stats.count
        self.processed += batch_stats.processed
        self.created += batch_stats.created
        self.updated += batch_stats.updated
        self.no_update_needed += batch_stats.no_update_needed
        self.document_updated += batch_stats.document_updated
        self.cancelled += batch_stats.cancelled
        self.document_error += batch_stats.document_error
        self.errors.extend(batch_stats.errors)


class HeartbeatManager:
    """Manages periodic heartbeat signals."""
    
    def __init__(self, interval_seconds: int = 10):
        self.interval_seconds = interval_seconds
        self.last_heartbeat = datetime.now()
    
    def should_heartbeat(self) -> bool:
        """Check if heartbeat is needed and update timestamp if so."""
        now = datetime.now()
        if (now - self.last_heartbeat).total_seconds() > self.interval_seconds:
            self.last_heartbeat = now
            return True
        return False


class PublicationFetcher:
    """Handles fetching and saving publications."""
    
    def __init__(self, processor, document_service, max_workers_download, max_retry_batch):
        self.processor = processor
        self.document_service = document_service
        self.max_workers_download = max_workers_download
        self.max_retry_batch = max_retry_batch
    
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
        """
        Fetch and save publications with retry logic.
        
        Yields status messages and None for heartbeat signals.
        """
        try:
            yield from self._process_publications(
                from_publication_date=from_publication_date,
                to_publication_date=to_publication_date,
                publication_zipcode=publication_zipcode,
                vat=vat,
                max_fetched_page_count=max_fetched_page_count,
                cancellation_event=cancellation_event,
                attempt=attempt + 1,
            )
        except Exception as e:
            logger.error("Error saving publications: %s", str(e), exc_info=True)
            traceback.print_exc()
            raise
    
    def _process_publications(
        self,
        *,
        from_publication_date,
        to_publication_date,
        publication_zipcode,
        vat,
        max_fetched_page_count,
        cancellation_event: Event,
        attempt: int,
    ) -> Generator[str | None, None, None]:
        """Process all publication batches."""
        heartbeat = HeartbeatManager(interval_seconds=10)
        total_stats = PublicationStats()
        
        for publication_batch in self.processor.process(
            from_publication_date=from_publication_date,
            to_publication_date=to_publication_date,
            publication_zipcode=publication_zipcode,
            vat=vat,
            max_fetched_page_count=max_fetched_page_count,
            cancellation_event=cancellation_event,
        ):
            if heartbeat.should_heartbeat():
                yield None
            
            if not publication_batch:
                continue
            
            # Process batch and yield status
            batch_stats = self._process_batch(
                publication_batch, cancellation_event, heartbeat
            )
            total_stats.add_batch(batch_stats)
            
            # Log and yield batch results
            message = batch_stats.format_message("Batch of")
            data = batch_stats.to_dict("batch_publications_")
            data["batch_documents_updated"] = batch_stats.document_updated
            
            if batch_stats.document_error > 0:
                logger.error(message, extra=data)
            else:
                logger.info(message, extra=data)
            yield message
        
        # Log final results
        yield from self._finalize_processing(
            total_stats,
            from_publication_date,
            to_publication_date,
            publication_zipcode,
            vat,
            max_fetched_page_count,
            cancellation_event,
            attempt,
        )
    
    def _process_batch(
        self,
        publication_batch,
        cancellation_event: Event,
        heartbeat: HeartbeatManager,
    ) -> PublicationStats:
        """Process a single batch of publications."""
        stats = PublicationStats(count=len(publication_batch))
        
        logger.info("Saving a batch of %s publications.", stats.count)
        
        for update_result in self.document_service.batch_update_publication_documents_from_moniteur_belge(
            publications=publication_batch,
            max_workers=self.max_workers_download,
            cancellation_event=cancellation_event,
        ):
            stats.processed += 1
            self._update_stats_from_result(stats, update_result)
            
            if heartbeat.should_heartbeat():
                # In a generator context, we'd yield None here
                pass
        
        return stats
    
    def _update_stats_from_result(self, stats: PublicationStats, update_result):
        """Update statistics based on update result."""
        result_handlers = {
            "OK_CREATED_SUCCESSFULLY": lambda: setattr(stats, 'created', stats.created + 1),
            "OK_UPDATED_SUCCESSFULLY": lambda: setattr(stats, 'updated', stats.updated + 1),
            "OK_NO_NEED_TO_UPDATE": lambda: setattr(stats, 'no_update_needed', stats.no_update_needed + 1),
            "OK_DOCUMENT_UPDATED_SUCCESSFULLY": lambda: setattr(stats, 'document_updated', stats.document_updated + 1),
            "CANCELLED": lambda: setattr(stats, 'cancelled', stats.cancelled + 1),
        }
        
        result_name = update_result.name if hasattr(update_result, 'name') else str(update_result)
        
        if result_name in result_handlers:
            result_handlers[result_name]()
        elif hasattr(update_result, 'value') and update_result.value.startswith("ERROR"):
            stats.document_error += 1
            stats.errors.append(update_result.value)
        else:
            logger.error("Internal Error: unknown update publication document result %s", update_result)
    
    def _finalize_processing(
        self,
        total_stats: PublicationStats,
        from_publication_date,
        to_publication_date,
        publication_zipcode,
        vat,
        max_fetched_page_count,
        cancellation_event: Event,
        attempt: int,
    ) -> Generator[str | None, None, None]:
        """Finalize processing and handle retries if needed."""
        # Log final statistics
        message = total_stats.format_message("TOTAL")
        data = total_stats.to_dict("publications_")
        
        if total_stats.document_error > 0:
            logger.error("Scan finished with errors.", extra=data)
        else:
            logger.info("Scan finished.", extra=data)
        yield message
        
        # Check for incomplete publications and retry if needed
        num_incomplete = self._incomplete_publications(
            from_publication_date,
            to_publication_date,
            publication_zipcode,
            vat,
        )
        
        if num_incomplete > 0:
            if attempt <= self.max_retry_batch:
                logger.warning(
                    "%s incomplete publications, retry number %s",
                    num_incomplete,
                    attempt,
                )
                yield from self._fetch_and_save_publications(
                    from_publication_date=from_publication_date,
                    to_publication_date=to_publication_date,
                    publication_zipcode=publication_zipcode,
                    vat=vat,
                    max_fetched_page_count=max_fetched_page_count,
                    cancellation_event=cancellation_event,
                    attempt=attempt,
                )
            else:
                error_message = (
                    f"Max Retry Limit has been reached, "
                    f"it was not possible to download files for {num_incomplete} publications"
                )
                logger.error(error_message)
                yield error_message
    
    def _incomplete_publications(
        self,
        from_publication_date,
        to_publication_date,
        publication_zipcode,
        vat,
    ) -> int:
        """
        Check for incomplete publications.
        This is a placeholder - implement based on your actual logic.
        """
        # TODO: Implement actual incomplete publications check
        return 0
