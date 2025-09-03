  File "/mnt/code/bnppf_guardrails/utils.py", line 50, in next_message_stream
    async for response in self.underlying_assistant.next_message_stream(conversation=conversation, **kwargs):
  File "/mnt/code/bnppf_rag_engine/rag_engine/use_cases/samy_emp/assistant.py", line 135, in next_message_stream
    async for response in self.generate_llm_answer_stream(conversation, user_id):
  File "/mnt/code/bnppf_rag_engine/rag_engine/use_cases/samy_emp/assistant.py", line 244, in generate_llm_answer_stream
    response=Message(role=MessageRole.ASSISTANT, content=content)
  File "/opt/conda/envs/aisc-ap04/lib/python3.10/typing.py", line 957, in __call__
    result = self.__origin__(*args, **kwargs)
  File "/opt/conda/envs/aisc-ap04/lib/python3.10/typing.py", line 957, in __call__
    result = self.__origin__(*args, **kwargs)
  File "/opt/conda/envs/aisc-ap04/lib/python3.10/typing.py", line 387, in __call__
    raise TypeError(f"Cannot instantiate {self!r}")
TypeError: Cannot instantiate typing.Union


class DocumentChunk(BaseModel):
    """A chunk of a document, indexed in a vector store or other database.

    Its goal is to have all the metadata possible so that it is self-contained and no
    downstream step needs to have access to the original document to do what they want with the chunk.

    An important distinction is between the "key" and the "content" of a chunk:
        - The content is the information that this chunk carries. It is, for example, the text
        that will be shown to the LLM in a RAG pipeline.
        - The key is the text used to retrieve this chunk from a database such as a vector store.
        For example, the key might be a single sentence, but the content it refers to might be
        the entire section which contains this sentence.

    Attributes:
        key: The text used to embed and retrieve this chunk.
        content: The informational content carried by this chunk.
        document_id: A unique id of the document this chunk is extracted from.
        span_in_document: The span of this chunk within the Document, used to sort, concatenate and merge chunks.
            This span should be **left-inclusive and right-exclusive**, e.g. the span of the string "el" in "hello"
            is (1, 3)

            When applicable, it should correspond to the character span of the chunk within the markdown representation of the document.
            But some chunks might not correspond exactly to a string span within the Document, in which case it is the DocumentChunker's role
            to output spans that are coherent and will give reasonable results when used downstream to sort, concatenate and merge
            chunks.

            See the "merge_chunks" function below for more details on how this span is used.
        tables: A list of tables contained within this chunk, in the order in which they appear.
        images: A list of images contained within this chunk, in the order in which they appear.
        hyperlinks: A list of links contained within this chunk.
        header_ancestry: A list of headers going from highest depth (top-level title) to lowest (current section's title)
            e.g. ["Section 2: foo", "Sub-section 1: bar", "sub-sub-section 3: baz"].
        headers_before: A list of the headers of the same level as the one containing this chunk, which
            come before the one containing this chunk.
        position_in_header_tree: A tuple of ints symbolizing this chunk's position in the tree of headers.
            For example, if this chunk is in the first subsection of the third section, the tuple would be (2, 0).
            Can be obtained from a Section object via the attribute of the same name.
            If specified, allows you to use the reconstitute_document_structure function.
        metadata: Any additional metadata necessary for downstream tasks.
            An alternative to using this field is subclassing this class.
    """

    key: str
    content: str
    document_id: str
    span_in_document: Span
    tables: list[TableBlock] = Field(default_factory=list)
    images: list[ImageBlock] = Field(default_factory=list)
    hyperlinks: list[Hyperlink] = Field(default_factory=list)
    header_ancestry: list[TitleBlock] = Field(default_factory=list)
    headers_before: list[TitleBlock] = Field(default_factory=list)
    position_in_header_tree: Optional[tuple[int, ...]] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_span_length(self) -> Self:
        """Verify that the length of the span_in_document is equal to the length of the chunk's content.
        Note: this implicitly checks that the span is valid, i.e. the second element is greater than the first.
        """
        span_length = len(self.span_in_document)
        if span_length != len(self.content):
            raise ValueError(
                f"The length implied by span_in_document ({span_length}) is different from the length of the content ({len(self.content)})."
            )
        return self

    @model_validator(mode="after")
    def check_position_in_header_tree_is_coherent(self) -> Self:
        """Verify that the position_in_header_tree attribute is coherent with the header_ancestry and
        headers_before attributes.
        """
        # Nothing to check if the attribute is not present
        if self.position_in_header_tree is None:
            return self

        if len(self.header_ancestry) != len(self.position_in_header_tree):
            raise ValueError("`header_ancestry` and `position_in_header_tree` should be the same length.")

        if self.position_in_header_tree and (len(self.headers_before) != self.position_in_header_tree[-1]):
            raise ValueError(
                "The last element of `position_in_header_tree` should be equal to the length of `headers_before`."
            )

        return self

    def __lt__(self, other: "DocumentChunk") -> bool:
        """We define the "<" operator so that chunks can be natively sorted using their position in the document.

        Note that this comparison does not make sense if the chunks are not from the same document.
        """
        return self.span_in_document.tuple < other.span_in_document.tuple

    @property
    def previous_headers(self) -> list[TitleBlock]:
        """Combine the header_ancestry with the headers_before to give the full sequence of headers
        up to this chunk including the ones before it in the same section.
        """
        return self.header_ancestry[:-1] + self.headers_before + self.header_ancestry[-1:]

    @property
    def header_ancestry_localized(self) -> list[LocalizedHeader]:
        """Same as header_ancestry, but returns LocalizedHeader objects instead of titles."""
        if self.position_in_header_tree is None:
            raise ValueError("To call this function, `position_in_header_tree` must not be None.")

        return [
            LocalizedHeader(header=header, position_in_header_tree=self.position_in_header_tree[: i + 1])
            for i, header in enumerate(self.header_ancestry)
        ]

    @property
    def headers_before_localized(self) -> list[LocalizedHeader]:
        """Same as headers_before, but returns LocalizedHeader objects instead of titles."""
        if self.position_in_header_tree is None:
            raise ValueError("To call this function, `position_in_header_tree` must not be None.")

        return [
            LocalizedHeader(header=header, position_in_header_tree=(*self.position_in_header_tree[:-1], i))
            for i, header in enumerate(self.headers_before)
        ]

    @property
    def previous_headers_localized(self) -> list[LocalizedHeader]:
        """Same as previous_headers, but returns LocalizedHeader objects instead of titles."""
        if self.position_in_header_tree is None:
            raise ValueError("To call this function, `position_in_header_tree` must not be None.")

        return self.header_ancestry_localized[:-1] + self.headers_before_localized + self.header_ancestry_localized[-1:]


class ConfidenceScore(BaseModel):
    """Confidence score information.

    Attributes:
        does_context_contain_answer: True if the context contains information to completely answer the question
        is_answer_correct_and_satisfying: True if business LLMJ finds the answer correct ans satisfying
        contradicting_information_output: information about contradiction detection
        confidence_grade: grade of the confidence score
    """

    does_context_contain_answer: bool | str  # str is temporary until we have context completness implemented
    is_answer_correct_and_satisfying: bool
    contradicting_information_output: ContradictionInformationOutput
    confidence_grade: Literal["low", "medium", "high"]

class Message(ConfiguredBaseModel):
    """Message schema."""

    role: MessageRole
    content: str

    def to_rag_toolbox(self) -> RTMessage:
        """Helper: convert to RAG-Toolbox object."""
        match self.role:
            case MessageRole.SYSTEM:
                return SystemMessage(content=self.content)
            case MessageRole.ASSISTANT:
                return AssistantMessage(content=self.content)
            case MessageRole.USER:
                return UserMessage(content=self.content)
            case _:
                raise NotImplementedError
				
class Metadata(ConfiguredBaseModel):
    """Metadata Schema for yara samy response."""

    confidence_score: ConfidenceScore | None
    prompt: Prompt | None
    keyword_search: bool
    references: list[DocumentChunk] | None

class YaraSamyResponse(ConfiguredBaseModel):
    """Yara for Samy API Response Schema."""

    response: Message | None = None
    metadata: Metadata | None = None


yield YaraSamyResponse(
	response=Message(role=MessageRole.ASSISTANT, content=content)
	
Here is the content value = "Le coût du pack Easy Go est de 2€ par mois. Le premier paiement est effectué au début du mois suivant l’enregistrement. Il est important de noter que les options disponibles pour le pack Easy Go, telles que la carte de débit supplémentaire, la carte de crédit, les transactions manuelles illimitées et l'assurance compte, sont payantes et ont des coûts spécifiques :\n\n- Carte de débit supplémentaire : 1,20€ par carte et par mois\n- Carte de crédit : \n  - Visa Classic : 2,25€ par carte et par mois\n  - Mastercard Gold : 4,25€ par carte et par mois\n- Transactions manuelles illimitées : 5€ par mois\n- Assurance compte : 4,25€ par an\n\nCependant, il est mentionné que les options seront gratuites pour tous les clients jusqu'au 31/12/2024. Il est donc possible que le coût du pack Easy Go et de ses options soit temporairement réduit ou annulé pendant cette période. Il est recommandé de vérifier les conditions et les tarifs actuels pour obtenir des informations à jour.\nPour avoir plus d'information, je vous conseille de lire les références ci-dessous."
)
