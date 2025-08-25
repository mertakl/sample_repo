def body_element(filepath: str) -> list[docx.oxml.text.paragraph.CT_P]:
    """Return body element of a docx filepath used to get xml."""
    return docx.Document(filepath)._body._body.xpath(".//w:p")  # pylint: disable=W0212

ef get_titles(self, filepath: str) -> dict[str, int]:
        """Extracts the titles of the document.

        The document 'main' title will have depth=0.

        Args:
            filepath: the local path to the documents

        Returns:
            titles with key title and value depth
        """
        titles = {}
        for item in body_element(filepath=filepath):
            title_depth = depth_from_xml(str(item.xml))
            if isinstance(title_depth, int) and item.text.split("\t")[0].strip():
                titles[item.text.split("\t")[0].strip()] = title_depth
        return 
