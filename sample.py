from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

def generate_valid_eureka_docx(filepath: str, language: str = "fr"):
    """
    Generates a .docx file that will pass update_titles_and_depths_eureka_nota.
    
    Args:
        filepath (str): Where to save the docx
        language (str): 'fr' or 'nl' for table of contents text
    """
    doc = Document()

    # === Main Title (depth 0) ===
    title = doc.add_paragraph("Eureka Knowledge Document")
    title.style = "Heading 1"
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # === Subtitle (depth 1) ===
    subtitle = doc.add_paragraph("Technical Guidelines")
    subtitle.style = "Heading 2"
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_paragraph()  # spacer

    # === Table of Contents ===
    toc_text = "table des matières" if language == "fr" else "inhoudsopgave"
    toc = doc.add_paragraph(toc_text)
    toc.style = "Heading 2"

    doc.add_paragraph("1. Introduction ........................................ 1")
    doc.add_paragraph("2. Methodology ...................................... 3")
    doc.add_paragraph("3. Results ............................................... 5")
    doc.add_paragraph("4. Conclusion ......................................... 8")

    doc.add_paragraph()  # spacer

    # === Document Body with Headings and Text ===
    h2 = doc.add_paragraph("Introduction")
    h2.style = "Heading 2"

    doc.add_paragraph("This section introduces the purpose of the Eureka document.")

    h3 = doc.add_paragraph("Background")
    h3.style = "Heading 3"
    doc.add_paragraph("Some background information goes here.")

    h2b = doc.add_paragraph("Methodology")
    h2b.style = "Heading 2"
    doc.add_paragraph("Details about the methodology.")

    h2c = doc.add_paragraph("Results")
    h2c.style = "Heading 2"
    doc.add_paragraph("Results of the analysis.")

    h2d = doc.add_paragraph("Conclusion")
    h2d.style = "Heading 2"
    doc.add_paragraph("Final conclusions and recommendations.")

    # Save the document
    doc.save(filepath)
    print(f"✅ DOCX generated at: {filepath}")


if __name__ == "__main__":
    generate_valid_eureka_docx("eureka_valid.docx", language="fr")
