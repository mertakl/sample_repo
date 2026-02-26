# config_registry.py

class ConfigRegistry:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def initialize(self):
        self.llm = get_llm_config()
        self.vector_db = get_vector_db_config()
        self.retriever = get_retriever_config()
        self.embedding_model = get_embedding_config()
        self.document = get_document_config()
        self.messages = get_messages_config()

configs = ConfigRegistry()
