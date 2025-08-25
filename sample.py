import re

def depth_from_xml(xml: str) -> int | None:
    """
    Get depth from XML.
    """
    # Use regular expressions to match Heading styles and extract their level
    match_heading = re.search(r'<w:pStyle w:val="Heading(\d+)"', xml)
    if match_heading:
        return int(match_heading.group(1)) - 1  # -1 for 0-based depth
    
    # Check for the specific Subtitle style
    if '<w:pStyle w:val="Subtitle"/>' in xml:
        return 0

    # Match TOC entries
    match_depth = re.search(r'<w:pStyle w:val="Contents([1-9]\d*)"', xml)
    if match_depth and "__RefHeading___Toc" in xml:
        return int(match_depth.group(1))
    
    return None
