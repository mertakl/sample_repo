except (ValueError, TypeError, OSError, ParsingError, DocumentError) as e:
    file_name = doc.file.get("Name", "Unknown File")
    logger.error("Error occurred while parsing document %s: %s", file_name, str(e))
    unparsable_docs_log[source].append(f"{file_name} because {e!s}")
except Exception as e:  # noqa: S110 - Catch-all for unexpected errors
    file_name = doc.file.get("Name", "Unknown File")
    logger.error("Unexpected error occurred while parsing document %s: %s", file_name, str(e))
    unparsable_docs_log[source].append(f"{file_name} because {e!s}")
