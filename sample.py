In the following code;

  def _convert_doc_to_docx_locally(self, doc_path: Path, output_dir: Path) -> Path | None:
        """Converts a .doc file to .docx."""
        try:
            subprocess.run(
                ["lowriter", "--headless", "--convert-to", "docx", str(doc_path), "--outdir", str(output_dir)],
                check=True,
                capture_output=True,  # Capture stdout/stderr
            )
            # The output file with .docx extension
            docx_path = output_dir / f"{doc_path.stem}.docx"
            if docx_path.exists():
                logger.info("Successfully converted %s to %s", doc_path.name, docx_path.name)
                return docx_path
            logger.error("Conversion failed for %s, output file not found.", doc_path.name)
            return None
        except FileNotFoundError:
            logger.error("`lowriter` command not found. Is LibreOffice installed and in your PATH?")
            return None
        except subprocess.CalledProcessError as e:
            logger.error("Error during .doc to .docx conversion for %s: %s", doc_path.name, e.stderr.decode())
            return None

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

                # Convert it to .docx
                converted_docx_path = self._convert_doc_to_docx_locally(temp_doc_path, temp_dir_path)

                if not converted_docx_path:
                    raise ParsingError(f"Failed to convert {file_name} from .doc to .docx")

                path_to_parse = converted_docx_path
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
			
##Instead of using inner _convert_doc_to_docx_locally. Is it possible to use this inside another file?

def convert_doc_to_docx_locally(filepath: str | Path, path_to_docx: str | Path) -> None:
    """Converts a file or a folder of .doc to .docx format.

    Args:
        filepath: path to a single .doc or to a folder with one or several .doc (without *.doc)
        path_to_docx: path to a folder where the .docx will be written
    """
    subprocess.run(["lowriter", "--convert-to", "docx", f"{filepath}", "--outdir", f"{path_to_docx}"], check=False)

