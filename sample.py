def write_metadata_bulk(
    self,
    documents: list[SharepointDocument],
    metadata_path: str,
) -> pd.DataFrame:
    """Write metadata for multiple documents to CSV file in a single pass."""
    logger.info("Writing bulk metadata for %d documents.", len(documents))

    # Build all new entries at once
    new_entries = []
    for document in documents:
        metadata = document.model_dump()
        metadata["uid"] = document.uid  # not in model_dump as it's a property
        new_entries.append(metadata)

    new_entries_df = pd.DataFrame(new_entries)

    # Load existing metadata once (instead of once per document)
    if self.cos_api.file_exists(metadata_path):
        df_metadata = read_csv(metadata_path, sep=";", cos_client=self.cos_api)
    else:
        df_metadata = self._create_empty_dataframe(columns=new_entries[0])

    # Remove all updated uids in one shot
    uids_to_update = set(new_entries_df["uid"])
    df_metadata = df_metadata[~df_metadata["uid"].isin(uids_to_update)]

    return pd.concat([df_metadata, new_entries_df], ignore_index=True)
