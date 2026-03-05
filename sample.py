from typing import Any, Iterator
from pydantic import ValidationError

class DocumentSkipError(Exception):
    """Custom exception to signal a document should be skipped during processing."""
    pass

class DocumentFetcher: # Assuming your class name
    def process_documents(
        self, items: list[dict[str, Any]], library: str, subfolder: str
    ) -> Iterator[SharepointDocument]:
        """Process items and yield valid documents, catching skips gracefully."""
        for item in items:
            document = self._build_document(item, library, subfolder)
            if document:
                yield document

    def _extract_metadata(self, item: dict[str, Any]) -> dict[str, Any]:
        """
        Extract raw metadata. 
        Raises DocumentSkipError if structural keys are missing.
        """
        try:
            list_item = item["ListItemAllFields"]
            server_relative_url = item["ServerRelativeUrl"]
            return {
                "name": item["Name"].lower(),
                "server_relative_url": server_relative_url,
                "author": item["Author"]["Title"],
                "time_last_modified": item["TimeLastModified"],
                "url": f"{self.config.site_base}{server_relative_url}?web=1",
                "title": list_item["Title"],
                "nota_number": list_item["UID"],
                "language": list_item["Language"],
                "approval_status": list_item["OData__ModerationStatus"],
            }
        except KeyError as e:
            self._miss_log.info(
                "%s missing metadata key: %s.", item.get("Name", "Unknown"), e
            )
            raise DocumentSkipError()

    def _validate_nota_name(self, metadata: dict[str, Any]) -> None:
        """Raise DocumentSkipError if the filename language is unrecognized."""
        if extract_language_from_filename(metadata["name"]) not in NOTA_LANGUAGE_MAP:
            self._miss_log.info(
                "Language of %s not in %s.", metadata["name"], list(NOTA_LANGUAGE_MAP)
            )
            raise DocumentSkipError()

    def _validate_required_values(self, metadata: dict[str, Any]) -> None:
        """Raise DocumentSkipError if required metadata values are empty."""
        missing = [k for k, v in metadata.items() if k != "approval_status" and not v]
        if missing:
            self._miss_log.info("Document %s has empty fields: %s.", metadata["name"], missing)
            raise DocumentSkipError()

    def _validate_eligibility(self, metadata: dict[str, Any]) -> None:
        """Check for language support, approval, and file extension."""
        name = metadata["name"]
        lang = metadata["language"]
        status = metadata["approval_status"]

        if lang not in LANGUAGE_MAPPING:
            self._skip_log.info("%s: Language '%s' unsupported.", name, lang)
            raise DocumentSkipError()

        if status != 0:
            self._skip_log.info("%s: Status '%s' is not approved.", name, status)
            raise DocumentSkipError()

        if not is_parseable(name):
            self._skip_log.info("%s: Extension not in %s.", name, PARSEABLE_EXTENSIONS)
            raise DocumentSkipError()

    def _build_document(
        self, item: dict[str, Any], library: str, subfolder: str
    ) -> SharepointDocument | None:
        """Linear pipeline to build a document. Returns None if any step raises Skip."""
        try:
            # 1. Extraction
            metadata = self._extract_metadata(item)

            # 2. Sequential Validations (Logic is flat)
            self._validate_nota_name(metadata)
            self._validate_required_values(metadata)
            self._validate_eligibility(metadata)

            # 3. Preparation & Instantiation
            metadata.pop("approval_status", None)
            
            # Dynamically inject folder rights
            rights_metadata = {
                field: does_folder_has_group(saml_group=field, folder=subfolder)
                for field in INEURights.list_filtering_metadata()
            }

            return SharepointDocument(
                **metadata,
                library=library,
                subfolder=subfolder,
                **rights_metadata
            )

        except DocumentSkipError:
            # Validation failed and was already logged; move to next item
            return None
        except ValidationError as e:
            # Catch Pydantic schema mismatches
            self._miss_log.error("Schema mismatch for %s: %s", item.get("Name"), e)
            return None
        except Exception as e:
            # Catch-all for unexpected logic errors to prevent loop crash
            self._miss_log.critical("Unexpected error processing %s: %s", item.get("Name"), e)
            return None
