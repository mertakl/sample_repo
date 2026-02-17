_SEARCH_TYPE_RULES: dict[str, dict] = {
    "semantic": {
        "required": ["semantic_database"],
        "forbidden": ["lexical_database", "semantic_proportion_before_reranker"],
    },
    "lexical": {
        "required": ["lexical_database"],
        "forbidden": ["semantic_database", "semantic_proportion_before_reranker"],
    },
    "hybrid": {
        "required": ["semantic_database", "lexical_database", "semantic_proportion_before_reranker"],
        "forbidden": [],
    },
}

@model_validator(mode="after")
def validate(self) -> Self:
    """Validates reranking setup and required parameters given the search_type."""
    self._validate_search_k()
    self._validate_search_type()
    return self

def _validate_search_k(self) -> None:
    if self.reranking_model is not None and self.search_k is None:
        raise ValueError("search_k attribute is required if a reranking model is used.")
    if self.search_k is not None and self.search_k < self.max_k:
        raise ValueError("search_k must be >= max_k")

def _validate_search_type(self) -> None:
    rules = _SEARCH_TYPE_RULES.get(self.search_type)
    if rules is None:
        raise ValueError(f"Unknown search_type: {self.search_type!r}")

    for field in rules["required"]:
        if getattr(self, field) is None:
            raise ValueError(
                f"{field} must be provided when search_type is {self.search_type!r}"
            )

    for field in rules["forbidden"]:
        if getattr(self, field) is not None:
            raise ValueError(
                f"Do not provide {field} when search_type is {self.search_type!r}"
            )
