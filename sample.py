import logging
from typing import List
from pathlib import Path
from tempfile import TemporaryDirectory
import os

from rag_toolbox.chunk_database import Bm25InMemoryDatabase
from your_module import (  # Replace with your actual imports
    BaseSearchAdapter,
    SearchQuery,
    QueryResponse,
    Document,
    DocumentChunk,
    ChunkFilterClause,
    Configuration,
    AVAILABLE_LANGUAGES_TYPE,
    SimpleCosClient,
    CosBucketApi,
    DocumentSplitter,
)

logger = logging.getLogger(__name__)


class BM25SearchAdapter(BaseSearchAdapter):
    """
    Adapter for BM25-based search using in-memory database.
    """
    bm25_db: Bm25InMemoryDatabase
    language: str
    nb_retrieved_doc_factor: int = 1

    def __init__(
        self,
        configuration: Configuration,
        language: AVAILABLE_LANGUAGES_TYPE,
        bm25_db: Bm25InMemoryDatabase,
        nb_retrieved_doc_factor: int = 1,
        **kwargs
    ):
        super().__init__(configuration=configuration, **kwargs)
        self.bm25_db = bm25_db
        self.language = language
        self.nb_retrieved_doc_factor = nb_retrieved_doc_factor

    @classmethod
    async def from_documents(
        cls,
        configuration: Configuration,
        language: AVAILABLE_LANGUAGES_TYPE,
        cos_bucket_api: SimpleCosClient | CosBucketApi,
        data_source_to_documents: dict[str, list[Document]] | None = None,
        nb_retrieved_doc_factor: int = 1,
    ) -> "BM25SearchAdapter":
        """
        Create BM25SearchAdapter by building index from document objects.
        """
        version_folder_name = cls._v_cos_patch(configuration.cos_version)

        if data_source_to_documents is None:
            data_source_to_documents = cls._read_parsed_documents_from_cos(
                cos_bucket_api=cos_bucket_api,
                configuration=configuration,
                version_folder_name=version_folder_name,
                language=language,
            )

        document_splitter = DocumentSplitter(
            splitter_config=configuration.document_splitter
        )

        documents: list[Document] = [
            document
            for documents in data_source_to_documents.values()
            for document in documents
        ]

        chunks: list[DocumentChunk] = await document_splitter.split_documents(
            documents=documents
        )

        bm25_db = Bm25InMemoryDatabase.from_documents(
            chunks,
            nb_retrieved_doc_factor=nb_retrieved_doc_factor
        )

        logger.info(f"Built BM25 index from {len(chunks)} chunks for language: {language}")

        return cls(
            configuration=configuration,
            language=language,
            bm25_db=bm25_db,
            nb_retrieved_doc_factor=nb_retrieved_doc_factor,
        )

    @classmethod
    def from_saved_index(
        cls,
        configuration: Configuration,
        language: AVAILABLE_LANGUAGES_TYPE,
        cos_bucket_api: SimpleCosClient | CosBucketApi,
    ) -> "BM25SearchAdapter":
        """
        Create BM25SearchAdapter by loading a saved index from COS.
        """
        version_folder_name = cls._v_cos_patch(configuration.cos_version)
        path_to_database = cls._get_cos_bm25_directory(
            configuration=configuration,
            language=language,
            version_folder_name=version_folder_name
        )

        if not cls._bm25_exists_on_cos(
            configuration=configuration,
            language=language,
            cos_bucket_api=cos_bucket_api
        ):
            raise FileNotFoundError(f"{path_to_database} is not a valid BM25 backup.")

        logger.info(f"Loading BM25 db for {language}")

        with TemporaryDirectory() as tmp_dir_name:
            cls._download_bm25_files(
                cos_bucket_api=cos_bucket_api,
                path_to_database=path_to_database,
                tmp_dir_name=tmp_dir_name,
                configuration=configuration,
            )

            bm25_db = Bm25InMemoryDatabase.load(path=tmp_dir_name, mmap=True)

        logger.info(f"Successfully loaded BM25 index for {language}")

        return cls(
            configuration=configuration,
            language=language,
            bm25_db=bm25_db,
        )

    async def search(self, query: SearchQuery, max_k: int = 10) -> List[QueryResponse]:
        """
        Perform BM25 search using the in-memory database.
        """
        try:
            # Assuming bm25_db.search returns list of tuples (Document, score)
            # Adjust based on actual return type of Bm25InMemoryDatabase.search
            results = await self.bm25_db.search(query.text, k=max_k)
            
            # Convert results to QueryResponse objects
            responses = []
            for doc, score in results:
                response = self.create_query_response(doc, score)
                responses.append(response)
            
            logger.info(f"BM25 search returned {len(responses)} results for query: {query.text}")
            return responses

        except Exception as e:
            logger.error(f"BM25 search failed: {e}", exc_info=True)
            return []

    async def select(self, filter_clauses: List[ChunkFilterClause]):
        """
        Implement selection logic if needed for BM25.
        Note: BM25 in-memory database may not support traditional filtering.
        """
        logger.warning("Select operation not implemented for BM25SearchAdapter")
        pass

    # --- Helper methods for COS operations ---

    @staticmethod
    def _v_cos_patch(cos_version: str) -> str:
        """Helper to format COS version folder name."""
        # Implement your version patching logic
        return cos_version

    @staticmethod
    def _read_parsed_documents_from_cos(
        cos_bucket_api: SimpleCosClient | CosBucketApi,
        configuration: Configuration,
        version_folder_name: str,
        language: AVAILABLE_LANGUAGES_TYPE,
    ) -> dict[str, list[Document]]:
        """Read parsed documents from COS."""
        # Implement your document reading logic
        from your_module import read_parsed_documents_from_cos
        
        return read_parsed_documents_from_cos(
            cos_bucket_api=cos_bucket_api,
            document_object_cos_folder=Path(
                configuration.document_parser.document_object_cos_folder
            ),
            v_cos_patch=version_folder_name,
            language=language,
            sources=list(configuration.document_parser.sources.keys()),
        )

    @staticmethod
    def _get_cos_bm25_directory(
        configuration: Configuration,
        language: AVAILABLE_LANGUAGES_TYPE,
        version_folder_name: str,
    ) -> str:
        """Get COS path for BM25 directory."""
        from your_module import get_cos_bm25_directory
        
        return get_cos_bm25_directory(
            configuration=configuration,
            language=language,
            version_folder_name=version_folder_name
        )

    @staticmethod
    def _bm25_exists_on_cos(
        configuration: Configuration,
        language: AVAILABLE_LANGUAGES_TYPE,
        cos_bucket_api: SimpleCosClient | CosBucketApi,
    ) -> bool:
        """Check if BM25 index exists on COS."""
        from your_module import bm25_exists_on_cos
        
        return bm25_exists_on_cos(
            configuration=configuration,
            language=language,
            cos_bucket_api=cos_bucket_api
        )

    @staticmethod
    def _download_bm25_files(
        cos_bucket_api: SimpleCosClient | CosBucketApi,
        path_to_database: str,
        tmp_dir_name: str,
        configuration: Configuration,
    ):
        """Download BM25 files from COS to temporary directory."""
        if isinstance(cos_bucket_api, SimpleCosClient):
            from decouple import config
            bucket_name = config("AISC_AP04_COS_BUCKET_NAME", default=config("BUCKET"))
            
            for cos_filename in cos_bucket_api.client.Bucket(bucket_name).objects.filter(
                Prefix=path_to_database
            ):
                filename = os.path.basename(str(cos_filename.key))
                file_path = str(Path(tmp_dir_name) / filename)
                cos_bucket_api.download_file(
                    key=str(cos_filename.key),
                    file_path=file_path
                )
        else:
            for cos_filename in cos_bucket_api.list_files_in_bucket_folder(
                path_to_database
            ):
                filename = Path(cos_filename).name
                cos_bucket_api.download_file(
                    cos_filename=cos_filename,
                    local_filename=str(Path(tmp_dir_name) / filename)
                )
