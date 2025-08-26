    async def _parse_documents(
        self, language: str, new_documents: list[ProcessedDocument], project_name: str
    ) -> dict[str, list[Document]]:
        """Parses a list of new documents, grouping them by their source."""
        docs_by_source = defaultdict(list)
        for doc in new_documents:
            docs_by_source[doc.source].append(doc)

        parsed_docs_by_source = defaultdict(list)
        unparsable_docs_log = defaultdict(list)

        for source, docs_to_parse in docs_by_source.items():
            for doc in docs_to_parse:
                try:
                    parsed_doc = await self._parse_document_content(
                        sp_file=doc.file, content=doc.content, source=source, language=language
                    )
                    if parsed_doc:
                        parsed_docs_by_source[source].append(parsed_doc)
                except ValueError as ve:
                    file_name = doc.file.get("Name", "Unknown File")
                    logger.error("Value error occurred while parsing document %s: %s", file_name, str(ve))
                    unparsable_docs_log[source].append(f"{file_name} because {ve!s}")
                except TypeError as te:
                    file_name = doc.file.get("Name", "Unknown File")
                    logger.error("Type error occurred while parsing document %s: %s", file_name, str(te))
                    unparsable_docs_log[source].append(f"{file_name} because {te!s}")
                except OSError as ioe:
                    file_name = doc.file.get("Name", "Unknown File")
                    logger.error("OS error occurred while parsing document %s: %s", file_name, str(ioe))
                    unparsable_docs_log[source].append(f"{file_name} because {ioe!s}")
                except Exception as e:
                    file_name = doc.file.get("Name", "Unknown File")
                    logger.error("Unexpected error occurred while parsing document %s: %s", file_name, str(e))
                    unparsable_docs_log[source].append(f"{file_name} because {e!s}")

        for source, unparsable in unparsable_docs_log.items():
            self.parser.write_unparsed_docs(unparsable, source, language, project_name)

        return parsed_docs_by_source
		
	Catching too general exception Exception from SONAR. How to disable sonar to scan?
