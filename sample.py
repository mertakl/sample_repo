

##I need a code to generate a docx file to pass following code when update_titles_and_depths_eureka_nota;
SHOULD_KEEP_NOT_FORMATTED_DOCUMENTS = False

PARSER_NAME_TO_OBJECT = {
    "HtmlParser": HtmlParser,
    "EurekaDocxParser": EurekaDocxParser,
    "DoclingParser": DoclingParser,
}

TABLE_OF_CONTENT = {
    "fr": [
        "table des matières",
        "table de matières",
        "table de matière",
        "tabie des matières",
        "contenu",
        "table des matière",
        "tables des matières",
    ],
    "nl": [
        "inhoudsopgave",
        "inhoudstafel",
        "inhoud",
        "inhoudsopgav",
        "inhoudstabel",
        "inhoudsopave",
    ],
}


class FormatError(Exception):
    """Exception linked to document formatting."""

    ...  # pylint: disable=W2301


class DocumentParser:
    """Class to manage the parsing of the documents."""

    def __init__(self, config_handler: ConfigHandler) -> None:
        """Initialize the DocumentParser class with a specific configuration.

        Args:
            config_handler (ConfigHandler): Configuration handler
        """
        self.config_handler = config_handler
        self.parser_config = config_handler.get_config("document_parser")
        self.data_source_enum = config_handler.get_source_enum()
        self.document_object_cos_folder = self.parser_config["document_object_cos_folder"]

    async def parse_all_documents_from_cos(
        self,
        cos_folder_path: str,
        language: AVAILABLE_LANGUAGES_TYPE,
        cos_bucket_api: CosBucketApi,
        should_write_unparsed_docs: bool,
        document_difference_threshold: float,
    ) -> dict[str, list[Document]]:
        """Parses both KBM et Eureka documents.

        Args:
            cos_folder_path (str): Path to the COS folder containing the documents
            language: language of the documents
            cos_bucket_api: object to interact with the COS
            should_write_unparsed_docs: bool to know if we should write the file
            document_difference_threshold: cutoff distance score between 2 documents

        Returns:
            A dictionary with the source as keys and the list Documents as values
        """
        filepaths_to_ignore: list[str] = get_duplicate_file_candidates_from_cos(
            output_path=OUTPUTS_PATH,
            score_threshold=document_difference_threshold,
            cos_bucket_api=cos_bucket_api,
            config_handler=self.config_handler,
        )

        document = {}
        for source in self.parser_config["sources"].keys():
            document[source] = await self.parse_one_source_from_cos(
                cos_folder_path=cos_folder_path,
                source=source,
                language=language,
                cos_bucket_api=cos_bucket_api,
                should_write_unparsed_docs=should_write_unparsed_docs,
                filepaths_to_ignore=filepaths_to_ignore,
                project_name=self.config_handler.get_config("project_name"),
            )

        return document

    async def parse_one_source_from_cos(
        self,
        cos_folder_path: str,
        project_name: str,
        source: "self.enum_type",
        language: AVAILABLE_LANGUAGES_TYPE,
        cos_bucket_api: CosBucketApi,
        should_write_unparsed_docs: bool,
        filepaths_to_ignore: list[str],
    ) -> list[Document]:
        """Chooses which type of parsing to use depending on config.

        Args:
            cos_folder_path (str): Path to the COS folder containing the documents
            project_name: Project name
            source: source of the documents
            language: language of the documents
            cos_bucket_api: object to interact with the COS
            should_write_unparsed_docs: bool to know if we should write the file
            filepaths_to_ignore: list of document paths to ignore

        Returns:
            list[Document]: A list of parsed documents.

        Raises:
            ValueError: If the parser type is not supported.
        """
        if self.parser_config["type"] == "rag_toolbox":
            return await self.parse_one_source_from_cos_rag_toolbox(
                cos_folder_path=cos_folder_path,
                source=source,
                language=language,
                project_name=project_name,
                cos_bucket_api=cos_bucket_api,
                should_write_unparsed_docs=should_write_unparsed_docs,
                filepaths_to_ignore=filepaths_to_ignore,
            )

        raise ValueError("Unsupported document parser type")

    async def parse_one_source_from_cos_rag_toolbox(  # pylint: disable=R0914
        self,
        cos_folder_path: str,
        source: "self.enum_type",
        language: AVAILABLE_LANGUAGES_TYPE,
        project_name: str,
        cos_bucket_api: CosBucketApi,
        should_write_unparsed_docs: bool,
        filepaths_to_ignore: list[str],
    ) -> list[Document]:
        """Parses documents from a COS folder.

        Args:
            cos_folder_path (str): Path to the COS folder containing the documents
            source: source of the documents
            language: fr or nl
            project_name: project_name
            cos_bucket_api: object to interact with the COS
            should_write_unparsed_docs: bool to know if we should write the file
            filepaths_to_ignore: list of document paths to ignore

        Returns:
            A list of parsed documents.

        Raises:
            ValueError: If the parser type is not supported.
        """
        file_extensions = self.parser_config["sources"][source]
        parsers_info = [self.parser_config["extension_to_parser_map"][extension] for extension in file_extensions]
        parsers = [PARSER_NAME_TO_OBJECT[parser_info["name"]](**parser_info["kwargs"]) for parser_info in parsers_info]
        max_documents_to_parse = self.parser_config.get("max_documents_to_parse", -1)
        parsed_docs = []
        unparsable_docs = []

        subfolders = self.parser_config["cos_bucket_subfolder"][source]
        for parser, subfolder in zip(parsers, subfolders):
            all_files = cos_bucket_api.list_files_in_bucket_folder(
                bucket_prefix=(
                    f"{cos_folder_path}/{source}/{subfolder}" if subfolder else f"{cos_folder_path}/{source}"
                ),
                recursive=True,
            )
            # Remove some files from all_files because they are too similar to other file
            all_files = [filepath for filepath in all_files if filepath not in filepaths_to_ignore]
            if max_documents_to_parse > 0 and len(parsed_docs) < max_documents_to_parse:
                all_files = all_files[: max_documents_to_parse - len(parsed_docs)]
            number_of_all_files = len(all_files)
            for filename in tqdm(all_files, f"Parsing {source} document in {language}"):
                parsed_file_or_error_msg = await self.parse_one_file_from_cos(
                    filename=filename,
                    cos_bucket_api=cos_bucket_api,
                    parser=parser,
                    source=source,
                    language=language,
                )
                if isinstance(parsed_file_or_error_msg, Document):
                    parsed_docs.append(parsed_file_or_error_msg)
                else:
                    unparsable_docs.append(parsed_file_or_error_msg)

        if should_write_unparsed_docs and unparsable_docs:
            self.write_unparsed_docs(
                unparsable_docs=unparsable_docs, source=source, language=language, project_name=project_name
            )
            logger.warning("The parser could not parse %d documents over %d", len(unparsable_docs), number_of_all_files)
            print(f"The parser could not parse {len(unparsable_docs)} documents over {number_of_all_files}")
        return parsed_docs

    async def parse_one_file_from_cos(
        self, filename: str, cos_bucket_api: CosBucketApi, parser: FileParser, source: str, language: str
    ) -> Document | str:
        """Parses one file from COS.

        Returns: tuple with the status & the parser document or the error
        """
        with TemporaryDirectory() as folder:
            file_path = Path(folder) / Path(filename).name
            file_path.write_bytes(cos_bucket_api.read_file(cos_filename=filename).read())
            try:
                document = await parser.parse_as_document(path=file_path, id=file_path.name)
                if source == EUREKA:
                    document = update_titles_and_depths_eureka_nota(
                        document=document,
                        titles=get_titles(filepath=str(file_path)),
                        language=language,
                    )
                return document
            except (ValueError, AssertionError, FormatError) as e:
                logger.exception(e)
                logger.error("The parser could not parse document '%s'", file_path.name)
                print(f"The parser could not parse document '{file_path.name}'")
                return " because ".join([filename, str(e)])

    @staticmethod
    def write_unparsed_docs(
        unparsable_docs: list[str],
        source: "self.enum_type",
        language: AVAILABLE_LANGUAGES_TYPE,
        project_name: str,
    ) -> None:
        """Writes unparsed doc file locally."""
        folder_path = Path(f"/mnt/data/aisc-ap04/{project_name.lower()}")
        folder_path.mkdir(exist_ok=True, parents=True)
        with open(folder_path / f"unparsed_docs_{source}_{language}.txt", "w") as outfile:
            outfile.writelines(language + "\n")
            outfile.writelines(str(d) + "\n" for d in unparsable_docs)

    @staticmethod
    def concat_documents(document: dict[str, list[Document]]) -> list[Document]:
        """Concatenates the list of Documents to have only one list.

        Args:
            document: {key: kbm or eureka, values: list of documents}

        Returns:
            The concatenated documents
        """
        return [doc for doc_list in document.values() for doc in doc_list]


def body_element(filepath: str) -> list[docx.oxml.text.paragraph.CT_P]:
    """Return body element of a docx filepath used to get xml."""
    return docx.Document(filepath)._body._body.xpath(".//w:p")  # pylint: disable=W0212


def depth_from_xml(xml: str) -> int | None:
    """Get depth from XML."""
    # Use regular expressions to match Heading styles and extract their level
    match_heading = re.search(r'<w:pStyle w:val="Heading(\d+)"', xml)
    if match_heading:
        return int(match_heading.group(1)) - 1  # -1 for 0-based depth
    
    # Check for the specific Subtitle style
    if '<w:pStyle w:val="Subtitle"/>' in xml:
        return 0

    # Match TOC entries
    match_depth = re.search(r'<w:pStyle w:val="Contents([1-9]\d*)"', xml)
    if match_depth and "__RefHeading___Toc" in xml:
        return int(match_depth.group(1))
    
    return None


def get_titles(filepath: str) -> dict[str, int]:
    """Extracts the titles of the document.

    The document 'main' title will have depth=0.

    Args:
        filepath: the local path to the documents

    Returns:
        titles with key title and value depth
    """
    titles = {}
    for item in body_element(filepath=filepath):
        title_depth = depth_from_xml(str(item.xml))
        if isinstance(title_depth, int) and item.text.split("\t")[0].strip():
            titles[item.text.split("\t")[0].strip()] = title_depth
    return titles


def return_document_or_raise(
    document: Document, failure_cause: str, should_keep_not_formatted_document: bool
) -> Document | None:
    """Returns document if we want to else raise error that will be caught in the try except."""
    if should_keep_not_formatted_document:
        return document
    raise FormatError(failure_cause)


def update_titles_and_depths_eureka_nota(
    document: Document,
    titles: dict[str, int],
    language: AVAILABLE_LANGUAGES_TYPE,
    should_keep_not_formatted_document: bool = SHOULD_KEEP_NOT_FORMATTED_DOCUMENTS,
) -> Document:
    """Improves the quality of the blocks on a document.

    More precisely, it:
        - reassigns titles and depths
        - update TitleBlocks that are actually TextBlocks
        - remove the block "table of content"
        - log the issue encountered so the document can be fixed

    Args:
        document: Parsed Document from Eureka
        titles: dict of titles to their depth
        language: language of the documents
        should_keep_not_formatted_document: True to keep wrongly formatted document without updating them

    Returns: New document with correct titles and depths
    """
    blocks = []
    main_title = ""
    main_subtitle = ""
    table_of_content_found = False

    if len(titles) == 0:
        return return_document_or_raise(
            document=document,
            failure_cause=f"0 titles found: {document.id}",
            should_keep_not_formatted_document=should_keep_not_formatted_document,
        )
    if max(titles.values()) == 0:
        return return_document_or_raise(
            document=document,
            failure_cause=f"No TOC: {document.id}",
            should_keep_not_formatted_document=should_keep_not_formatted_document,
        )

    for block in document.blocks:
        is_text_in_block = hasattr(block, "text")

        if not is_text_in_block:  # TableBlock -> add a TextBlock instead to use caption
            text_metadata = deepcopy(block.metadata)
            del text_metadata["caption"]
            text_metadata["is_llm_generated"] = True
            text_metadata["main_title"] = main_title
            text_metadata["main_subtitle"] = main_subtitle
            blocks.append(  # add new TextBlock to use caption in generation
                TextBlock(
                    hyperlinks=block.hyperlinks,
                    page=block.page,
                    faq_id=block.faq_id,
                    faq_role=block.faq_role,
                    metadata=text_metadata,
                    block_type="TextBlock",
                    text=block.metadata.get("caption", "Caption was not generated properly. Do not use this source."),
                )
            )
            block.metadata["main_title"] = main_title
            block.metadata["main_subtitle"] = main_subtitle
            block.metadata["is_llm_generated"] = False
            blocks.append(block)  # keep TableBlock
            continue

        stripped_text = block.text.strip()
        # if depth = 0 (document general title), we remove the chunk and add title in all chunk metadata
        if titles.get(stripped_text, -1) == 0:
            main_title, main_subtitle = update_document_titles(
                main_title=main_title, main_subtitle=main_subtitle, stripped_text=stripped_text, document_id=document.id
            )
            del titles[stripped_text]
        # remove block with the string "table of content"
        elif stripped_text.lower() in TABLE_OF_CONTENT[language]:
            table_of_content_found = True
        # it's a Textblock, TitleBlock, ListItem or CodeBlock
        elif stripped_text in titles:  # title is found -> transform to TitleBlock and update depth
            block.metadata["main_title"] = main_title
            block.metadata["main_subtitle"] = main_subtitle
            block.metadata["is_llm_generated"] = False
            blocks.append(
                TitleBlock(
                    hyperlinks=block.hyperlinks,
                    page=block.page,
                    faq_id=block.faq_id,
                    faq_role=block.faq_role,
                    metadata=block.metadata,
                    block_type="TitleBlock",
                    text=block.text,
                    depth=titles[stripped_text],
                )
            )
            del titles[stripped_text]
        # no title found -> transform TitleBlock to TextBlock (as only titles should be TitleBlock)
        elif block.block_type == "TitleBlock":
            block.metadata["main_title"] = main_title
            block.metadata["main_subtitle"] = main_subtitle
            block.metadata["is_llm_generated"] = False
            blocks.append(
                TextBlock(
                    hyperlinks=block.hyperlinks,
                    page=block.page,
                    faq_id=block.faq_id,
                    faq_role=block.faq_role,
                    metadata=block.metadata,
                    block_type="TextBlock",
                    text=stripped_text,
                )
            )
        else:  # keep Textblock, ListItem or CodeBlock and update the title
            block.metadata["main_title"] = main_title
            block.metadata["main_subtitle"] = main_subtitle
            block.metadata["is_llm_generated"] = False
            blocks.append(block)

    validation_output = validate_document_format(
        document=document,
        blocks=blocks,
        titles=titles,
        main_title=main_title,
        main_subtitle=main_subtitle,
        table_of_content_found=table_of_content_found,
        should_keep_not_formatted_document=should_keep_not_formatted_document,
    )

    return validation_output or Document(
        blocks=blocks,
        id=document.id,
        filename=document.filename,
        metadata=document.metadata,
    )


def validate_document_format(
    document: Document,
    blocks: list[Block],
    titles: dict[str, int],
    main_title: str,
    main_subtitle: str,
    table_of_content_found: bool,
    should_keep_not_formatted_document: bool,
) -> Document | None:
    """Validates (and returns if needed) document.

    Args:
        document: Parsed Document from Eureka
        blocks: updated blocks from the document
        titles: dict of titles to their depth
        main_title: main title of the document
        main_subtitle: main_subtitle of the document
        table_of_content_found: True if the string "table of content" was found
        should_keep_not_formatted_document: True to keep wrongly formatted document without updating them

    Return:
        - if should_keep_not_formatted_document is True:
            - Validation failed: original document
            - All validation passed: None
        - if should_keep_not_formatted_document is False:
            - Validation failed: raise FormatError that will be caught in the except
            - All validation passed: None
    """
    if not table_of_content_found:
        return return_document_or_raise(
            document=document,
            failure_cause=f"Table of content not found: {document.id}",
            should_keep_not_formatted_document=should_keep_not_formatted_document,
        )

    # validate all blocks have the same main_title and main_subtitle
    for block in blocks:
        if block.metadata["main_title"] != main_title:
            return return_document_or_raise(
                document=document,
                failure_cause=f"Not all blocks have the same main_title in {document.id}."
                "This means a document main title is missplaced.",
                should_keep_not_formatted_document=should_keep_not_formatted_document,
            )
        if block.metadata["main_subtitle"] != main_subtitle:
            return return_document_or_raise(
                document=document,
                failure_cause=f"Not all blocks have the same main_subtitle in {document.id}."
                "This means a document main title is missplaced.",
                should_keep_not_formatted_document=should_keep_not_formatted_document,
            )

    # validate all titles were found
    if len(titles) != 0:
        return return_document_or_raise(
            document=document,
            failure_cause=f"Titles not found in {document.id}: {titles}",
            should_keep_not_formatted_document=should_keep_not_formatted_document,
        )
    return None


def update_document_titles(
    main_title: str, main_subtitle: str, stripped_text: str, document_id: str
) -> tuple[str, str]:
    """Updates document main title and main subtitles."""
    if not main_title:
        main_title = stripped_text
    elif not main_subtitle:
        main_subtitle = stripped_text
    else:
        raise ValueError(
            f"Main title {main_title} and main subtitle {main_subtitle} already found for document {document_id}."
        )
    return main_title, main_subtitle
	
##Can you generate a script to do that?
