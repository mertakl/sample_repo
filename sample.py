def process_documents(
    self, items: list[dict[str, Any]], library: str, subfolder: str
) -> Iterator[SharepointDocument]:
    """Process items to extract relevant document information and yield valid documents."""
    for item in items:
        try:
            document = self._build_document(item, library, subfolder)
        except KeyError as e:
            self._miss_log.info(
                "%s is missing the following metadata: %s.",
                item.get("Name", "Name not found!"),
                e,
            )
            continue

        if document is not None:
            yield document

def _extract_metadata(self, item: dict[str, Any]) -> dict[str, Any]:
    """Extract and return raw metadata from a SharePoint item."""
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
        "approval_status": list_item["OData__ModerationStatus"],  # 0 for approved
    }

def _validate_metadata_fields(self, metadata: dict[str, Any]) -> None:
    """Raise if the metadata keys don't match SharepointDocument.model_fields."""
    required_fields = {
        *{k for k in metadata if k != "approval_status"},
        "library",
        "subfolder",
        *INEURights.list_filtering_metadata(),
    }
    if required_fields != set(SharepointDocument.model_fields):
        raise DocumentFetcherException(
            "Sharepoint metadata does not match SharepointDocument fields. "
            "Please update one of the two."
        )

def _has_valid_nota_name(self, metadata: dict[str, Any]) -> bool:
    """Log and return False if the nota filename language is not recognised."""
    if extract_language_from_filename(metadata["name"]) not in NOTA_LANGUAGE_MAP:
        self._miss_log.info(
            "Language of %s should be in %s.",
            metadata["name"],
            list(NOTA_LANGUAGE_MAP),
        )
        return False
    return True

def _has_no_missing_values(self, metadata: dict[str, Any]) -> bool:
    """Log and return False if any required metadata value is empty."""
    missing = [k for k, v in metadata.items() if k != "approval_status" and not v]
    if missing:
        self._miss_log.info(
            "Document %s has empty metadata for %s.",
            metadata["name"],
            missing,
        )
        return False
    return True

def _is_eligible(self, metadata: dict[str, Any]) -> bool:
    """Log and return False if the document should be skipped."""
    approval_status = metadata["approval_status"]
    if not (
        metadata["language"] in LANGUAGE_MAPPING
        and approval_status == 0
        and is_parseable(metadata["name"])
    ):
        self._skip_log.info(
            "%s was skipped because either: "
            "1) Language '%s' is not supported, "
            "2) Approval_status '%s' is not 0, "
            "3) Extension is not supported (only %s).",
            metadata["name"],
            metadata["language"],
            approval_status,
            PARSEABLE_EXTENSIONS,
        )
        return False
    return True

def _build_document(
    self, item: dict[str, Any], library: str, subfolder: str
) -> SharepointDocument | None:
    """Return a SharepointDocument if the item passes all checks, else None."""
    metadata = self._extract_metadata(item)
    self._validate_metadata_fields(metadata)

    if not self._has_valid_nota_name(metadata):
        return None
    if not self._has_no_missing_values(metadata):
        return None
    if not self._is_eligible(metadata):
        return None

    return SharepointDocument(
        **{k: v for k, v in metadata.items() if k != "approval_status"},
        library=library,
        subfolder=subfolder,
        **{
            field: does_folder_has_group(saml_group=field, folder=subfolder)
            for field in INEURights.list_filtering_metadata()
        },
    )
