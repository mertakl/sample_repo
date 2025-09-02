from pathlib import Path
import tempfile
import logging
from your_module import convert_doc_to_docx_locally  # Import the external function

logger = logging.getLogger(__name__)

async def _parse_document_content(
        self, sp_file: dict, content: bytes, source: str, language: str
) -> Document | None:
    """Parses a single document's content, converting .doc to .docx if necessary."""
    file_name = sp_file.get("Name")
    if not file_name:
        logger.warning("SharePoint file has no name, cannot parse.")
        return None

    original_extension = Path(file_name).suffix.lstrip(".").lower()
    parser_config = self.parser.parser_config

    # Determine the effective extension for parsing (.doc becomes .docx)
    parse_extension = "docx" if original_extension == "doc" else original_extension

    if parse_extension not in parser_config["sources"].get(source, []):
        logger.warning("File extension '.%s' not supported for source '%s'.", original_extension, source)
        return None

    # Get the appropriate parser for the target format (.docx)
    parser_info = parser_config["extension_to_parser_map"][parse_extension]
    file_parser = PARSER_NAME_TO_OBJECT[parser_info["name"]](**parser_info["kwargs"])

    # Temporary directory to handle original, converted, and output files
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        path_to_parse: Path

        if original_extension == "doc":
            # Write .doc content to a temporary file
            temp_doc_path = temp_dir_path / file_name
            temp_doc_path.write_bytes(content)

            # Convert it to .docx using the external function
            try:
                convert_doc_to_docx_locally(temp_doc_path, temp_dir_path)
                
                # Check if the conversion was successful
                converted_docx_path = temp_dir_path / f"{temp_doc_path.stem}.docx"
                if not converted_docx_path.exists():
                    raise ParsingError(f"Failed to convert {file_name} from .doc to .docx - output file not found")
                
                logger.info("Successfully converted %s to %s", temp_doc_path.name, converted_docx_path.name)
                path_to_parse = converted_docx_path
                
            except Exception as e:
                logger.error("Error during .doc to .docx conversion for %s: %s", file_name, str(e))
                raise ParsingError(f"Failed to convert {file_name} from .doc to .docx: {str(e)}")
        else:
            # Write original content to a temp file
            temp_file_path = temp_dir_path / file_name
            temp_file_path.write_bytes(content)
            path_to_parse = temp_file_path

        # Parse the final document
        document = await file_parser.parse_as_document(path=path_to_parse, id=file_name)

        if source == EUREKA:
            # Apply source-specific post-processing
            document = update_titles_and_depths_eureka_nota(
                document=document,
                titles=get_titles(filepath=str(path_to_parse)),  # Use the parsed file path
                language=language,
            )
        return document
