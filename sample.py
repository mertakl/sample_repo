except Exception as e:  # pylint: disable=broad-exception-caught
            file_name = doc.file.get("Name", unknown_file)
            logger.error("Unexpected error occurred while parsing document %s: %s", file_name, str(e))
            unparsable_docs_log[source].append(f"{file_name} because {e!s}")
