import traceback

for source, docs_to_parse in docs_by_source.items():
    for doc in docs_to_parse:
        try:
            parsed_doc = await self._parse_document_content(
                sp_file=doc.file, content=doc.content, source=source, language=language
            )
            if parsed_doc:
                parsed_docs_by_source[source].append(parsed_doc)
        except (ValueError, TypeError, OSError, ParsingError) as e:
            file_name = doc.file.get("Name", unknown_file)
            # Get the full traceback
            tb_str = traceback.format_exc()
            logger.error("Error occurred while parsing document %s: %s\nTraceback:\n%s", 
                        file_name, str(e), tb_str)
            unparsable_docs_log[source].append(f"{file_name} because {e!s}")
        except Exception as e:
            file_name = doc.file.get("Name", unknown_file)
            # Get the full traceback
            tb_str = traceback.format_exc()
            logger.error("Unexpected error occurred while parsing document %s: %s\nTraceback:\n%s", 
                        file_name, str(e), tb_str)
            unparsable_docs_log[source].append(f"{file_name} because {e!s}")
