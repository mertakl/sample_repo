import docx
from docx.shared import Pt

def create_valid_docx(filename: str = "valid_document.docx"):
    """
    Generates a DOCX file that is structured to pass the validation checks
    in the `update_titles_and_depths_eureka_nota` function.
    """
    document = docx.Document()

    # 1. Add a Main Title (depth=0)
    # The get_titles() function detects 'Heading 1' as depth 0.
    document.add_heading("Nota Fiscaal Jaar 2025", level=1)

    # 2. Add a Subtitle (depth=0)
    # The get_titles() function detects the 'Subtitle' style as depth 0.
    document.add_paragraph("Analyse en Aanbevelingen", style='Subtitle')

    document.add_paragraph("Dit is een inleidende paragraaf die geen titel is.")

    # 3. Add the "Table of Contents" text
    # This is required to pass the `table_of_content_found` check.
    # We use the Dutch version from your TABLE_OF_CONTENT dictionary.
    document.add_paragraph("Inhoudsopgave")

    # 4. Add a primary section title (depth=1)
    # This 'Heading 2' ensures that `max(titles.values()) > 0`, passing the TOC check.
    document.add_heading("Hoofdstuk 1: Analyse van de Inkomsten", level=2)
    document.add_paragraph(
        "De inkomsten voor het fiscale jaar 2025 vertonen een positieve trend. "
        "Deze sectie bevat een gedetailleerde uitsplitsing."
    )
    document.add_paragraph("Nog een paragraaf met normale tekst.")

    # 5. Add a subsection title (depth=2)
    # 'Heading 3' is detected as depth 2.
    document.add_heading("Paragraaf 1.1: Directe Inkomsten", level=3)
    document.add_paragraph(
        "De directe inkomsten zijn met 5% gestegen ten opzichte van vorig jaar."
    )

    # 6. Add another primary section title (depth=1)
    document.add_heading("Hoofdstuk 2: Analyse van de Uitgaven", level=2)
    document.add_paragraph(
        "De uitgaven zijn onder controle gebleven, met een lichte stijging "
        "in de operationele kosten."
    )
    
    # Save the document
    try:
        document.save(filename)
        print(f"Successfully created '{filename}'")
    except Exception as e:
        print(f"Error saving file: {e}")

if __name__ == "__main__":
    create_valid_docx()
