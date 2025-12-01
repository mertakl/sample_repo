
def build_retriever(
    config_handler: ConfigHandler,
    language: AVAILABLE_LANGUAGES_TYPE,
    semantic_database: ChunkDatabase | None = None,
    lexical_database: ChunkDatabase | None = None,
    reranker: Reranker | None = None,
) -> Retriever:
    assert (
        semantic_database is not None or lexical_database is not None
    ), "You must give at least a semantic database and a lexical database."
    
    retriever_config = config_handler.get_config("retriever")
    max_k: int = retriever_config["k"]
    search_k: int = retriever_config["search_k"]
    add_reranking: bool = "reranking_model" in retriever_config
    retriever_object_config = RetrieverConfig(max_k=max_k)
    search_type = retriever_config["search_type"]
    
    # Helper function for semantic/lexical cases
    def _build_single_db_retriever(database: ChunkDatabase) -> Retriever:
        if add_reranking:
            return RerankDatabaseRetriever(
                retriever_config=retriever_object_config,
                database=database,
                reranker=reranker,
                search_max_k=search_k,
            )
        return DefaultRetriever(retriever_config=retriever_object_config, database=database)
    
    match search_type:
        case "hybrid":
            if retriever_config["lexical_database"] == "is_vector":
                return TsVectorRetriever(
                    config_handler=config_handler,
                    database=semantic_database,
                    reranker=reranker,
                    language=language,
                )
            return HybridSearchRetriever(
                retriever_config=retriever_object_config,
                semantic_proportion_before_reranker=retriever_config["semantic_proportion_before_reranker"],
                search_k_before_reranker=search_k,
                database=semantic_database,
                lexical_database=lexical_database,
                reranker=reranker,
            )
        case "semantic":
            return _build_single_db_retriever(semantic_database)
        case "lexical":
            return _build_single_db_retriever(lexical_database)
        case _:
            raise ValueError("Your retriever search type should be one of the following: hybrid, semantic, lexical.")
