------config/configs/llm.py
from dataclasses import dataclass
from django.conf import settings


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model_name: str
    api_key: str
    temperature: float
    max_tokens: int
    timeout: int = 30

    @classmethod
    def from_dict(cls, config_dict: dict) -> 'LLMConfig':
        return cls(
            provider=config_dict['provider'],
            model_name=config_dict['model_name'],
            api_key=config_dict['api_key'],
            temperature=config_dict['temperature'],
            max_tokens=config_dict['max_tokens'],
            timeout=config_dict.get('timeout', 30),
        )

    @classmethod
    def get_main(cls) -> 'LLMConfig':
        return cls.from_dict(settings.LLM_CONFIG)

    @classmethod
    def get_evaluation(cls) -> 'LLMConfig':
        return cls.from_dict(settings.EVALUATION_LLM_CONFIG)

    @classmethod
    def get_guardrails(cls) -> 'LLMConfig':
        return cls.from_dict(settings.GUARDRAILS_LLM_CONFIG)


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str
    model_name: str
    api_key: str
    dimension: int
    batch_size: int

    @classmethod
    def from_settings(cls) -> 'EmbeddingConfig':
        config = settings.EMBEDDING_CONFIG
        return cls(
            provider=config['provider'],
            model_name=config['model_name'],
            api_key=config['api_key'],
            dimension=config['dimension'],
            batch_size=config['batch_size'],
        )

-------config/configs/retrieval.py
from dataclasses import dataclass
from django.conf import settings


@dataclass(frozen=True)
class VectorDBConfig:
    host: str
    port: int
    database: str
    user: str
    password: str
    table_name: str

    @classmethod
    def from_settings(cls) -> 'VectorDBConfig':
        config = settings.VECTOR_DB_CONFIG
        return cls(
            host=config['host'],
            port=config['port'],
            database=config['database'],
            user=config['user'],
            password=config['password'],
            table_name=config['table_name'],
        )

    @property
    def connection_string(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


@dataclass(frozen=True)
class RetrievalConfig:
    top_k: int
    score_threshold: float
    reranking_enabled: bool
    hybrid_search: bool

    @classmethod
    def from_settings(cls) -> 'RetrievalConfig':
        config = settings.RETRIEVAL_CONFIG
        return cls(
            top_k=config['top_k'],
            score_threshold=config['score_threshold'],
            reranking_enabled=config['reranking_enabled'],
            hybrid_search=config['hybrid_search'],
        )

---config/configs/document.py
from dataclasses import dataclass
from typing import Literal
from django.conf import settings


@dataclass(frozen=True)
class DocumentParserConfig:
    type: str
    extract_images: bool

    @classmethod
    def from_settings(cls) -> 'DocumentParserConfig':
        config = settings.DOCUMENT_CONFIG['parser']
        return cls(
            type=config['type'],
            extract_images=config['extract_images'],
        )


@dataclass(frozen=True)
class DocumentSplitterConfig:
    type: Literal['nested', 'sliding_window']
    chunk_size: int
    chunk_overlap: int

    @classmethod
    def from_settings(cls) -> 'DocumentSplitterConfig':
        config = settings.DOCUMENT_CONFIG['splitter']
        return cls(
            type=config['type'],
            chunk_size=config['chunk_size'],
            chunk_overlap=config['chunk_overlap'],
        )


@dataclass(frozen=True)
class DocumentConfig:
    parser: DocumentParserConfig
    splitter: DocumentSplitterConfig

    @classmethod
    def from_settings(cls) -> 'DocumentConfig':
        return cls(
            parser=DocumentParserConfig.from_settings(),
            splitter=DocumentSplitterConfig.from_settings(),
        )

------config/managers/prompts.py
import logging
from pathlib import Path
from typing import Optional
from django.conf import settings
from django.core.cache import caches

logger = logging.getLogger(__name__)


class PromptTemplate:
    def __init__(self, name: str, content: str):
        self.name = name
        self.content = content

    def format(self, **kwargs) -> str:
        return self.content.format(**kwargs)

    def __str__(self) -> str:
        return self.content


class PromptManager:
    def __init__(self, prompts_dir: Optional[Path] = None):
        self.prompts_dir = Path(prompts_dir or settings.PROMPTS_DIR)
        self.cache = caches['prompts']

    def _cache_key(self, name: str) -> str:
        return f"prompt:{name}"

    def _load_from_file(self, name: str) -> str:
        filepath = self.prompts_dir / f"{name}.txt"
        if not filepath.exists():
            raise FileNotFoundError(f"Prompt template not found: {filepath}")
        return filepath.read_text(encoding='utf-8')

    def get(self, name: str) -> PromptTemplate:
        cache_key = self._cache_key(name)
        cached = self.cache.get(cache_key)

        if cached:
            return cached

        try:
            content = self._load_from_file(name)
            prompt = PromptTemplate(name, content)
            self.cache.set(cache_key, prompt)
            return prompt
        except Exception as e:
            logger.error(f"Failed to load prompt '{name}': {e}")
            raise

    def reload(self, name: str) -> PromptTemplate:
        self.cache.delete(self._cache_key(name))
        return self.get(name)

    def clear_cache(self):
        self.cache.clear()

    # Convenience properties
    @property
    def system_rag(self) -> PromptTemplate:
        return self.get('rag/system')

    @property
    def user_query(self) -> PromptTemplate:
        return self.get('rag/user_query')

    @property
    def retrieval_query(self) -> PromptTemplate:
        return self.get('retrieval/query_generation')

    @property
    def keyword_search(self) -> PromptTemplate:
        return self.get('retrieval/keyword_search')


# Singleton
_prompt_manager: Optional[PromptManager] = None


def get_prompt_manager() -> PromptManager:
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager()
    return _prompt_manager

-------config/managers/messages.py
from typing import Literal
from django.conf import settings

AVAILABLE_LANGUAGES_TYPE = Literal['en', 'fr', 'de']


class MessageManager:
    """Simple manager for fixed, localized messages."""

    def get(self, key: str, language: AVAILABLE_LANGUAGES_TYPE = 'en', **kwargs) -> str:
        """Get a localized message, falling back to English."""
        messages = settings.MESSAGES_CONFIG.get(key, {})
        message = messages.get(language) or messages.get('en', key)

        if kwargs:
            return message.format(**kwargs)
        return message

    # Convenience methods
    def empty_input(self, language: AVAILABLE_LANGUAGES_TYPE = 'en') -> str:
        return self.get('empty_input', language)

    def empty_doc_input(self, language: AVAILABLE_LANGUAGES_TYPE = 'en') -> str:
        return self.get('empty_doc_input', language)

    def no_url_found(self, language: AVAILABLE_LANGUAGES_TYPE = 'en') -> str:
        return self.get('no_url_found', language)

    def url_found(self, language: AVAILABLE_LANGUAGES_TYPE = 'en', url: str = '') -> str:
        return self.get('url_found', language, url=url)


# Singleton
_message_manager: Optional[MessageManager] = None


def get_message_manager() -> MessageManager:
    global _message_manager
    if _message_manager is None:
        _message_manager = MessageManager()
    return _message_manager
