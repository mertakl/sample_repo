PROMPTS_DIR = BASE_DIR / 'prompts'

# Project
PROJECT_NAME = config('PROJECT_NAME', default='MyRAGProject')
COS_VERSION = config('COS_VERSION', default='1.0.0')

# LLM
LLM_CONFIG = {
    'provider': config('LLM_PROVIDER', default='openai'),
    'model_name': config('LLM_MODEL_NAME', default='gpt-4'),
    'api_key': config('LLM_API_KEY'),
    'temperature': config('LLM_TEMPERATURE', default=0.7, cast=float),
    'max_tokens': config('LLM_MAX_TOKENS', default=2000, cast=int),
    'timeout': config('LLM_TIMEOUT', default=30, cast=int),
}

EVALUATION_LLM_CONFIG = {
    'provider': config('EVAL_LLM_PROVIDER', default='openai'),
    'model_name': config('EVAL_LLM_MODEL_NAME', default='gpt-4'),
    'api_key': config('EVAL_LLM_API_KEY', default=LLM_CONFIG['api_key']),
    'temperature': config('EVAL_LLM_TEMPERATURE', default=0.3, cast=float),
    'max_tokens': config('EVAL_LLM_MAX_TOKENS', default=1000, cast=int),
}

GUARDRAILS_LLM_CONFIG = {
    'provider': config('GUARDRAILS_LLM_PROVIDER', default='openai'),
    'model_name': config('GUARDRAILS_LLM_MODEL_NAME', default='gpt-3.5-turbo'),
    'api_key': config('GUARDRAILS_LLM_API_KEY', default=LLM_CONFIG['api_key']),
}

# Embedding
EMBEDDING_CONFIG = {
    'provider': config('EMBEDDING_PROVIDER', default='openai'),
    'model_name': config('EMBEDDING_MODEL_NAME', default='text-embedding-3-small'),
    'api_key': config('EMBEDDING_API_KEY', default=LLM_CONFIG['api_key']),
    'dimension': config('EMBEDDING_DIMENSION', default=1536, cast=int),
    'batch_size': config('EMBEDDING_BATCH_SIZE', default=32, cast=int),
}

# Vector DB
VECTOR_DB_CONFIG = {
    'host': config('VECTOR_DB_HOST', default='localhost'),
    'port': config('VECTOR_DB_PORT', default=5432, cast=int),
    'database': config('VECTOR_DB_NAME'),
    'user': config('VECTOR_DB_USER'),
    'password': config('VECTOR_DB_PASSWORD'),
    'table_name': config('VECTOR_DB_TABLE', default='embeddings'),
}

# Document Processing
DOCUMENT_CONFIG = {
    'parser': {
        'type': config('DOC_PARSER_TYPE', default='pdf'),
        'extract_images': config('DOC_EXTRACT_IMAGES', default=True, cast=bool),
    },
    'splitter': {
        'type': config('DOC_SPLITTER_TYPE', default='nested'),
        'chunk_size': config('DOC_CHUNK_SIZE', default=512, cast=int),
        'chunk_overlap': config('DOC_CHUNK_OVERLAP', default=50, cast=int),
    },
}

# Retrieval
RETRIEVAL_CONFIG = {
    'top_k': config('RETRIEVAL_TOP_K', default=5, cast=int),
    'score_threshold': config('RETRIEVAL_SCORE_THRESHOLD', default=0.7, cast=float),
    'reranking_enabled': config('RETRIEVAL_RERANKING', default=True, cast=bool),
    'hybrid_search': config('RETRIEVAL_HYBRID_SEARCH', default=True, cast=bool),
}

# Messages (fixed, not from env or i18n)
MESSAGES_CONFIG = {
    'empty_input': {
        'en': 'Please provide input',
        'fr': 'Veuillez fournir une entrée',
        'de': 'Bitte geben Sie eine Eingabe an',
    },
    'empty_doc_input': {
        'en': 'No document provided',
        'fr': 'Aucun document fourni',
        'de': 'Kein Dokument bereitgestellt',
    },
    'no_url_found': {
        'en': 'No URL found',
        'fr': 'Aucune URL trouvée',
        'de': 'Keine URL gefunden',
    },
    'url_found': {
        'en': 'URL found: {url}',
        'fr': 'URL trouvée: {url}',
        'de': 'URL gefunden: {url}',
    },
}
