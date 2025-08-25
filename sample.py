from pathlib import Path
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

def create_valid_docx(filename: str, lang: str = "en") -> Path:
    """
    Generates a DOCX file with a structure that satisfies the
    'update_titles_and_depths_eureka_nota' function.

    The generated document includes:
    - A main title and subtitle
    - A 'Table of Contents' entry (required for validation)
    - A Heading 1 and Heading 2 to be correctly recognized as titles.

    Args:
        filename (str): The name of the file to create (e.g., 'valid_doc.docx').
        lang (str): The language for the Table of Contents string ('fr' or 'nl').
    
    Returns:
        Path: The path to the created DOCX file.
    """
    
    # Define table of content text based on language
    table_of_content_text = ""
    if lang == "fr":
        table_of_content_text = "Table des matières"
    elif lang == "nl":
        table_of_content_text = "Inhoudsopgave"
    else:
        print("Invalid language. Using 'Table of Contents' as default.")
        table_of_content_text = "Table of Contents"

    # Create a new Document
    document = Document()

    # Add a main title with a custom style
    main_title_para = document.add_paragraph("Main Document Title", style="Title")
    main_title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    main_title_para.paragraph_format.space_before = Pt(12)

    # Add a main subtitle
    subtitle_para = document.add_paragraph("Document Subtitle", style="Subtitle")
    subtitle_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle_para.paragraph_format.space_after = Pt(24)

    # Add a table of contents entry. This is a crucial step for the
    # update_titles_and_depths_eureka_nota function to pass validation.
    # The 'TOC' is detected by specific keywords and the absence of a depth.
    toc_para = document.add_paragraph(table_of_content_text, style="Contents1")
    toc_para.alignment = WD_ALIGN_PARAGRAPH.LEFT
    
    # Add a paragraph with a regular Heading 1 style
    document.add_heading("Section 1: Introduction", level=1)
    document.add_paragraph("This is the introduction section.")

    # Add a paragraph with a regular Heading 2 style
    document.add_heading("Section 1.1: Details", level=2)
    document.add_paragraph("More details about the introduction.")
    
    # Add some regular body text
    document.add_paragraph("This is a simple text block.")

    # Save the document to the specified file
    filepath = Path(filename)
    document.save(filepath)

    print(f"✅ Successfully created DOCX file: {filepath.resolve()}")
    return filepath

if __name__ == "__main__":
    # Specify the name of the file to be created
    output_filename = "test_document_for_eureka_nota.docx"
    
    # Run the function to create the document
    create_valid_docx(output_filename, lang="fr")
