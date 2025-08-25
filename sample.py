from pathlib import Path
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

def create_valid_docx(filename: str, lang: str = "fr") -> Path:
    """
    Generates a DOCX file with a structure that satisfies the
    'update_titles_and_depths_eureka_nota' function.
    """
    
    document = Document()

    # Add a main title with a custom style. This is the only depth 0 title.
    document.add_paragraph("Main Document Title", style="Title")
    
    # Add a main subtitle.
    document.add_paragraph("Document Subtitle", style="Subtitle")
    
    # Define and add custom "Contents1" style if not present.
    custom_toc_style_name = 'Contents1'
    styles = document.styles
    if custom_toc_style_name not in [style.name for style in styles]:
        new_style = styles.add_style(custom_toc_style_name, WD_STYLE_TYPE.PARAGRAPH)
        new_style.font.name = 'Calibri'
        new_style.font.size = Pt(11)

    # Add the TOC entry.
    table_of_content_text = "Table des matières" if lang == "fr" else "Inhoudsopgave"
    document.add_paragraph(table_of_content_text, style=custom_toc_style_name)
    
    # Add regular headings.
    document.add_heading("Section 1: Introduction", level=1)
    document.add_paragraph("This is the introduction section.")

    document.add_heading("Section 1.1: Details", level=2)
    document.add_paragraph("More details about the introduction.")
    
    # Save the document.
    filepath = Path(filename)
    document.save(filepath)

    print(f"✅ Successfully created DOCX file: {filepath.resolve()}")
    return filepath

if __name__ == "__main__":
    output_filename = "test_document_for_eureka_nota.docx"
    create_valid_docx(output_filename, lang="fr")
