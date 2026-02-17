from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Parser models
# ---------------------------------------------------------------------------

class ParserEntry(BaseModel):
    """A single parser definition (parser_cls + kwargs)."""
    parser_cls: str
    kwargs: dict[str, Any] = Field(default_factory=dict)


class ParserConfig(BaseModel):
    type: str  # e.g. "rag_toolbox"

    # Source types per knowledge-base flavour
    sources: dict[str, list[str]]  # e.g. {"kbm": ["html"], "eureka": ["pdf", "docx"]}

    document_object_cos_folder: Path
    nota_url_cos_folder: Path

    # Maps file extension -> parser definition
    extension_to_parser_map: dict[str, ParserEntry]

    # Domain-name extractor per kb flavour (stored as raw strings / lambdas in
    # the original config; we keep them as plain strings here)
    source_to_domain_name_extractor: dict[str, str]

    cos_bucket_subfolder: dict[str, list[str]]

    # Files that should be loaded without a table-of-contents
    filename_without_toc: list[str] = Field(default_factory=list)

    # Maps a letter prefix to a human-readable product name
    eureka_title_letter_map: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Splitter models
# ---------------------------------------------------------------------------

class KeySplitterParams(BaseModel):
    chunk_size: int
    chunk_overlap: int


class KeySplitter(BaseModel):
    type: str  # e.g. "RecursiveCharacterTextSplitter"
    params: KeySplitterParams


class SectionChunker(BaseModel):
    max_title_depth: int
    size_threshold: int
    include_links: bool


class SplitterConfig(BaseModel):
    algorithm: str  # e.g. "nested"
    key_splitter: KeySplitter
    section_chunker: SectionChunker
    split_oversized_content: bool = True
    content_overlap: int = 0


# ---------------------------------------------------------------------------
# Root config
# ---------------------------------------------------------------------------

class DocumentConfig(BaseModel):
    parser: ParserConfig
    splitter: SplitterConfig

    @classmethod
    def from_django_settings(cls) -> "DocumentConfig":
        """Convenience factory that reads DOCUMENT_CONFIG from Django settings."""
        from django.conf import settings  # noqa: PLC0415
        return cls(**settings.DOCUMENT_CONFIG)
