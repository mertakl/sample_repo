@@In the following code;
...rest of the code


async def parse_documents(
    config_handler: ConfigHandler,
    language: AVAILABLE_LANGUAGES_TYPE,
    should_export_label_studio: bool,
    cos_bucket_api: CosBucketApi,
    should_write_unparsed_docs: bool,
    should_add_caption_for_table_blocks: bool,
    should_add_eureka_url_in_metadata: bool,
    document_difference_threshold: float,
    project_name: str,
) -> dict[str, list[Document]]:
    """Parses the documents."""
    parser = DocumentParser(config_handler)

    # Parser
    print(f"*****STARTING PARSING DOCUMENT IN {language}*****")
    data_source_to_documents = await parser.parse_all_documents_from_cos(
        cos_folder_path=f"refined/{V_COS_MINOR}/{language}",
        language=language,
        cos_bucket_api=cos_bucket_api,
        should_write_unparsed_docs=should_write_unparsed_docs,
        document_difference_threshold=document_difference_threshold,
    )
    print(f"*****FINISHING PARSING DOCUMENT IN {language}*****")

    # Caption for tables
    print(f"*****STARTING ADDING CAPTIONS FOR DOCUMENT IN {language}*****")
    if should_add_caption_for_table_blocks:
        data_source_to_documents = await add_caption_to_table_blocks(
            data_source_to_documents=data_source_to_documents,
            language=language,
            project_name=project_name,
        )
    print(f"*****FINISHING ADDING CAPTIONS FOR DOCUMENT IN {language}*****")

    # URLs for Eureka documents
    print(f"*****STARTING ADDING URLS FOR DOCUMENT IN {language}*****")
    if should_add_eureka_url_in_metadata:
        data_source_to_documents = add_url_in_metadata(data_source_to_documents=data_source_to_documents)
    print(f"*****FINISHING ADDING URLS FOR DOCUMENT IN {language}*****")

    if should_export_label_studio:
        export_label_studio_input(data_source_to_documents, project_name, language, config_handler=config_handler)

    return data_source_to_documents


async def parse_documents_and_save_or_read_cached_documents(  # pylint: disable=R0917, R0913
    config_handler: ConfigHandler,
    language: AVAILABLE_LANGUAGES_TYPE,
    should_export_label_studio: bool,
    cos_bucket_api: CosBucketApi,
    should_write_unparsed_docs: bool,
    should_add_caption_for_table_blocks: bool,
    should_add_eureka_url_in_metadata: bool,
    document_difference_threshold: float,
    project_name: str,
) -> dict[str, list[Document]]:
    """Parses documents and writes the generated vector DB on the COS."""
    sources = list(config_handler.get_config("document_parser")["sources"].keys())
    document_object_cos_folder = config_handler.get_config("document_parser")["document_object_cos_folder"]
    if should_use_cache_if_exists:
        data_source_to_documents = read_parsed_documents_from_cos(
            cos_bucket_api=cos_bucket_api,
            document_object_cos_folder=document_object_cos_folder,
            v_cos_patch=V_COS_PATCH,
            language=language,
            sources=sources,
        )
        if data_source_to_documents is not None:
            return data_source_to_documents

    data_source_to_documents = await parse_documents(
        config_handler=config_handler,
        language=language,
        cos_bucket_api=cos_bucket_api,
        should_write_unparsed_docs=should_write_unparsed_docs,
        should_add_caption_for_table_blocks=should_add_caption_for_table_blocks,
        should_export_label_studio=should_export_label_studio,
        should_add_eureka_url_in_metadata=should_add_eureka_url_in_metadata,
        document_difference_threshold=document_difference_threshold,
        project_name=project_name,
    )

    
	dump_model_on_cos(
		cos_bucket_api=cos_bucket_api,
		data_source_to_documents=data_source_to_documents,
		cos_folder_path=document_object_cos_folder,
		v_cos_patch=V_COS_PATCH,
		language=language,
		sources=sources,
		should_overwrite_on_cos=False,
	)

    return data_source_to_documents


def create_document_chunks(
    config_handler: ConfigHandler, data_source_to_documents: dict[str, list[Document]]
) -> list[DocumentChunk]:
    splitter = DocumentSplitter(config_handler.get_config("document_splitter"))
    documents = DocumentParser.concat_documents(document=data_source_to_documents)
    document_chunks = splitter.split_documents(documents)

    unique_keys = len({chunk.key for chunk in document_chunks})
    nb_keys = len(document_chunks)
    if unique_keys != nb_keys:
        warning_message = f"Duplicate keys found in document chunks: {unique_keys} unique keys for {nb_keys} chunks"

        warnings.warn(warning_message, stacklevel=2)

    return document_chunks


async def generate_vector_db(
    should_export_label_studio: bool,
    cos_bucket_api: CosBucketApi,
    config_handler: ConfigHandler,
    should_write_unparsed_docs: bool,
    should_add_caption_for_table_blocks: bool,
    should_add_eureka_url_in_metadata: bool,
    document_difference_threshold: float,
    language: str | None = None,
) -> None:
    # Language selection
    assert not (language), "Cannot upload to COS when language is explicitly given."
    languages = [language] if language else config_handler.get_config("languages")

    for lan in languages:
        data_source_to_documents: dict[str, list[Document]] = await parse_documents_and_save_or_read_cached_documents(
            config_handler=config_handler,
            language=lan,
            should_export_label_studio=should_export_label_studio,
            cos_bucket_api=cos_bucket_api,
            should_write_unparsed_docs=should_write_unparsed_docs,
            should_add_caption_for_table_blocks=should_add_caption_for_table_blocks,
            should_add_eureka_url_in_metadata=should_add_eureka_url_in_metadata,
            document_difference_threshold=document_difference_threshold,
            project_name=config_handler.get_config("project_name"),
        )

        document_chunks = create_document_chunks(config_handler, data_source_to_documents)

        vector_db = VectorDB(
            vector_db_config=config_handler.get_config("vector_db"),
            embedding_model=BNPPFEmbeddings(config_handler.get_config("embedding_model")),
            language=lan,
            project_name=config_handler.get_config("project_name"),
        )
        vector_db.setup_db_instance()
        # Important: start the DB from scratch for each language
        drop_and_resetup_vector_db(vector_db.vector_db_config)
        await vector_db.from_chunks(document_chunks)
        
		await vector_db.to_cos(cos_bucket_api, should_overwrite_on_cos=False)
        

...rest of the code

---document_parser.py
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
    """Get depth from XML.

    Args:
        xml: XmlString object of the body element

    Returns:
        depth if any or None
    """
    if '<w:pStyle w:val="Heading"/>' in xml or '<w:pStyle w:val="Subtitle"/>' in xml:  # main titles
        return 0
    match_depth = re.search(r'<w:pStyle w:val="Contents([1-9]\d*)"', xml)  # depth
    if match_depth and "__RefHeading___Toc" in xml:  # text in ToC
        return int(match_depth.group(1))
    return None  # not main titles nor ToC


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

	

## generate_vector_db is the main function to run. Which retrieves documents from ibm cos and saves to vector db.
##I need to do same in this code except I only need to save the new files to vector db 
##Here is the code that I am working on;
------client.py
class SharePointClient:
    """Main SharePoint client class."""

    def __init__(self, sp_config: SharePointConfig):  # noqa: D107
        self.config = sp_config
        self.cos_api = self._create_cos_api()

        # Initialize components
        self.azure_creds = self._initialize_azure_credentials()
        self.authenticator = SharePointAuthenticator(sp_config, self.azure_creds)
        self.api_client = SharePointAPIClient(sp_config, self.authenticator)
        self.metadata_manager = MetadataManager(self.cos_api)
        self.document_processor = DocumentProcessor(self.api_client, self.cos_api, self.metadata_manager)

    def run(self, project_args) -> None:
        """Main execution method."""
        config_handler = self._get_config_handler(project_args.project_name)
        languages = self._get_languages(project_args, config_handler)

        # Handle deleted files
        self._process_deleted_files()

        # Process documents by language
        grouped_documents = self._get_grouped_documents(["Documents"])

        for language in languages:
            documents = grouped_documents.get(language, {})
            self._process_documents_by_language(documents, project_args)

    def _process_deleted_files(self) -> None:
        """Process deleted files from recycle bin."""
        try:
            logger.info("Retrieving deleted files from sharepoint.")
            deleted_files = self._get_deleted_file_names()
            for file_name in deleted_files:
                self.document_processor.delete_document(file_name=file_name)
        except (ConnectionError, ValueError, KeyError) as e:
            logger.error("Failed to process deleted files: %s", e)

    def _process_documents_by_language(self, documents_by_source: dict[str, list[dict]], doc_args) -> None:
        """Process documents grouped by source for a specific language."""
        for source, doc_list in documents_by_source.items():
            for doc_data in doc_list:
                doc = ProcessedDocument(
                    file=doc_data["File"],
                    nota_number=doc_data.get("NotaNumber"),
                    source=source,
                    language=doc_data.get("Language", ""),
                )
                self.document_processor.process_document(doc=doc, parsed_args=doc_args)

    def _get_grouped_documents(self, libraries: list[str]) -> dict[str, dict[str, list[dict]]]:
        """Get documents grouped by language and source."""
        logger.info("Grouping documents by their source and language.")

        grouped_documents = defaultdict(lambda: defaultdict(list))

        for library in libraries:
            try:
			##Retrieve documents from sharepoint
                documents = self._retrieve_documents_from_library(library)
                for doc in documents:
                    language, source = doc["Language"], doc["Source"]
                    if language and source:
                        grouped_documents[language][source].append(doc)
            except (ConnectionError, KeyError, ValueError) as e:
                logger.error("Error processing library %s: %s", library, e)
                continue

        return grouped_documents
        ]


	..rest 

---document_processor.py
	
	class DocumentProcessor:
    """Processes SharePoint documents."""

    def __init__(  # noqa: D107
        self, api_client: SharePointAPIClient, cos_api: CosBucketApi, metadata_manager: MetadataManager
    ):
        self.api_client = api_client
        self.cos_api = cos_api
        self.metadata_manager = metadata_manager
        self.path_manager = PathManager()

    def process_document(self, doc: ProcessedDocument, parsed_args) -> None:
        """Process a single document."""
        file_info = doc.file
        file_name, last_modified, source, language = (
            file_info["Name"],
            file_info["TimeLastModified"],
            file_info["Source"],
            file_info["Language"],
        )

        file_path = self.path_manager.get_document_path(source=source, language=language, file_name=file_name)

        if not DocumentFilter.is_parseable(file_name):
            self._log_unparseable_document(file_name, doc, parsed_args)
            return

        if not DocumentFilter.is_recently_modified(last_modified):
            if not self.cos_api.file_exists(file_path):
                # TODO: If the file does not exist already
                self._upload_document(doc, file_path)
            return
        self._upload_document(doc, file_path)

    def delete_document(self, file_name: str) -> None:
        """Delete document from COS and update metadata."""
        metadata_path = self.path_manager.get_metadata_path()

        deleted_doc_metadata = self.metadata_manager.get_metadata_by_filename(
            file_name=file_name, metadata_path=metadata_path
        )

        if not deleted_doc_metadata:
            # Nothing to delete
            return

        # Delete file from COS
        source, language = deleted_doc_metadata["source"], deleted_doc_metadata["language"]
        file_path = self.path_manager.get_document_path(source=source, language=language, file_name=file_name)
        logger.info("Deleting file %s", file_name)
        self.cos_api.delete_file(str(file_path))

        # Remove from metadata
        self.metadata_manager.remove_metadata(metadata_path=metadata_path, file_name=file_name)

    def _upload_document(self, doc: ProcessedDocument, document_path: str) -> None:
        """Upload document to COS and save metadata."""
        file_info = doc.file
        file_name, server_relative_url = file_info["Name"], file_info["ServerRelativeUrl"]

        logger.info("Downloading document %s from sharepoint...", file_name)

        # Download file content
        file_content = self.api_client.download_file(server_relative_url)

        # Create temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_name)[1]) as temp_file:
            temp_file.write(file_content)
            temp_file_path = temp_file.name

        try:
            logger.info("Uploading document %s to COS...", file_name)
            # Upload to COS
            self.cos_api.upload_file(temp_file_path, document_path)

            # Save metadata
            metadata = DocumentMetadata(
                file_name=file_name,
                url=server_relative_url,
                created_by=file_info.get("Author"),
                last_modified=file_info["TimeLastModified"],
                nota_number=doc.nota_number,
                language=doc.language,
                source=doc.source,
            )

            metadata_path = self.path_manager.get_metadata_path()
            self.metadata_manager.write_metadata(metadata, metadata_path)

        finally:
            # Clean up temporary file
            os.unlink(temp_file_path)

    def _log_unparseable_document(self, file_name: str, doc: ProcessedDocument, p_args) -> None:
        """Log unparseable document."""
        DocumentParser.write_unparsed_docs(
            unparsable_docs=[file_name],
            source=doc.source,
            language=doc.language,
            project_name=p_args.project_name,
        )

        _, extension = os.path.splitext(file_name)
        logger.error("Files with extension '%s' are not supported", extension)
		
##So basically, I need you to save the files which are supposed to upload to COS. 
