
"""HTML processing and text extraction utilities."""

import re
from enum import Enum
from typing import List


class LatexConverterState(Enum):
    """State machine states for LaTeX conversion."""
    TEXT = "text"
    BACKSLASH = "backslash"
    INLINE_START = "inline_start"
    INLINE_CONTENT = "inline_content"
    INLINE_BACKSLASH = "inline_backslash"
    BLOCK_START = "block_start"
    BLOCK_CONTENT = "block_content"
    BLOCK_BACKSLASH = "block_backslash"


class LatexStreamConverter:
    r"""
    Streaming LaTeX converter using state machine.

    Converts \( ... \) → $ ... $ and \[ ... \] → $$ ... $$ character-by-character.
    Handles incomplete delimiters during streaming by buffering until complete.

    Usage:
        converter = LatexStreamConverter()
        for chunk in stream:
            converted = converter.process(chunk)
            yield converted
        final = converter.flush()  # Get any buffered content
    """

    WHITESPACE = frozenset(" \t")
    WHITESPACE_WITH_NEWLINE = frozenset(" \t\n")

    def __init__(self) -> None:
        """Initialize converter with TEXT state."""
        self.state = LatexConverterState.TEXT
        self.buffer = ""
        self.output = ""

    def process(self, chunk: str) -> str:
        """
        Process streaming chunk and return converted text ready to forward.

        Args:
            chunk: Text chunk from LLM stream

        Returns:
            Converted text (empty if buffering incomplete expression)
        """
        self.output = ""
        for char in chunk:
            self._process_char(char)
        
        result = self.output
        self.output = ""
        return result

    def flush(self) -> str:
        """
        Flush any buffered content at end of stream.

        Returns:
            Any remaining buffered text (unconverted if incomplete)
        """
        result = self.buffer
        self.buffer = ""
        self.state = LatexConverterState.TEXT
        return result

    def _process_char(self, char: str) -> None:
        """Process single character through state machine."""
        state_handlers = {
            LatexConverterState.TEXT: self._handle_text,
            LatexConverterState.BACKSLASH: self._handle_backslash,
            LatexConverterState.INLINE_START: self._handle_inline_start,
            LatexConverterState.INLINE_CONTENT: self._handle_inline_content,
            LatexConverterState.INLINE_BACKSLASH: self._handle_inline_backslash,
            LatexConverterState.BLOCK_START: self._handle_block_start,
            LatexConverterState.BLOCK_CONTENT: self._handle_block_content,
            LatexConverterState.BLOCK_BACKSLASH: self._handle_block_backslash,
        }
        handler = state_handlers[self.state]
        handler(char)

    def _handle_text(self, char: str) -> None:
        """Handle TEXT state."""
        if char == "\\":
            self.state = LatexConverterState.BACKSLASH
            self.buffer = "\\"
        else:
            self.output += char

    def _handle_backslash(self, char: str) -> None:
        """Handle BACKSLASH state."""
        if char == "(":
            self.state = LatexConverterState.INLINE_START
            self.buffer = ""
        elif char == "[":
            self.state = LatexConverterState.BLOCK_START
            self.buffer = ""
        else:
            self.output += self.buffer + char
            self.buffer = ""
            self.state = LatexConverterState.TEXT

    def _handle_inline_start(self, char: str) -> None:
        """Handle INLINE_START state - skip leading whitespace."""
        if char in self.WHITESPACE:
            pass  # Skip leading whitespace
        elif char == "\\":
            self.state = LatexConverterState.INLINE_BACKSLASH
            self.buffer += "\\"
        else:
            self.state = LatexConverterState.INLINE_CONTENT
            self.buffer += char

    def _handle_inline_content(self, char: str) -> None:
        """Handle INLINE_CONTENT state."""
        if char == "\\":
            self.state = LatexConverterState.INLINE_BACKSLASH
            self.buffer += "\\"
        else:
            self.buffer += char

    def _handle_inline_backslash(self, char: str) -> None:
        """Handle INLINE_BACKSLASH state."""
        if char == ")":
            self._close_inline_math()
        else:
            self.state = LatexConverterState.INLINE_CONTENT
            self.buffer += char

    def _handle_block_start(self, char: str) -> None:
        """Handle BLOCK_START state - skip leading whitespace."""
        if char in self.WHITESPACE_WITH_NEWLINE:
            pass  # Skip leading whitespace
        elif char == "\\":
            self.state = LatexConverterState.BLOCK_BACKSLASH
            self.buffer += "\\"
        else:
            self.state = LatexConverterState.BLOCK_CONTENT
            self.buffer += char

    def _handle_block_content(self, char: str) -> None:
        """Handle BLOCK_CONTENT state."""
        if char == "\\":
            self.state = LatexConverterState.BLOCK_BACKSLASH
            self.buffer += "\\"
        else:
            self.buffer += char

    def _handle_block_backslash(self, char: str) -> None:
        """Handle BLOCK_BACKSLASH state."""
        if char == "]":
            self._close_block_math()
        else:
            self.state = LatexConverterState.BLOCK_CONTENT
            self.buffer += char

    def _close_inline_math(self) -> None:
        """Close inline math expression and emit output."""
        content = self.buffer[:-1].rstrip(" \t")
        self.output += f"${content}$"
        self.buffer = ""
        self.state = LatexConverterState.TEXT

    def _close_block_math(self) -> None:
        """Close block math expression and emit output."""
        content = self.buffer[:-1]
        content = self._strip_block_whitespace(content)
        self.output += f"$${content}$$"
        self.buffer = ""
        self.state = LatexConverterState.TEXT

    @staticmethod
    def _strip_block_whitespace(content: str) -> str:
        """Strip trailing whitespace per line and empty leading/trailing lines."""
        lines = content.split("\n")
        stripped_lines = [line.rstrip(" \t") for line in lines]
        
        while stripped_lines and not stripped_lines[0].strip():
            stripped_lines.pop(0)
        while stripped_lines and not stripped_lines[-1].strip():
            stripped_lines.pop()
        
        return "\n".join(stripped_lines)


def convert_latex_to_dollar_signs(text: str) -> str:
    r"""
    Convert parenthesized LaTeX to dollar-sign delimited format.

    Transforms:
    - \( ... \) → $ ... $ (inline math)
    - \[ ... \] → $$ ... $$ (block/display math)

    This processes complete text. For streaming, use LatexStreamConverter.

    Args:
        text: Complete markdown text

    Returns:
        Text with LaTeX converted to dollar-sign delimiters

    Examples:
        >>> convert_latex_to_dollar_signs(r"The value \( \\frac{1}{2} \) is 0.5")
        'The value $\\\\frac{1}{2}$ is 0.5'

        >>> convert_latex_to_dollar_signs(r"\[ E = mc^2 \]")
        '$$E = mc^2$$'
    """
    converter = LatexStreamConverter()
    result = converter.process(text) + converter.flush()
    return result


class HtmlStripper:
    """HTML tag removal and entity decoding."""

    HTML_ENTITIES = {
        "&lt;": "<",
        "&gt;": ">",
        "&amp;": "&",
        "&quot;": '"',
        "&#39;": "'",
        "&nbsp;": " ",
    }

    HTML_STRUCTURES = {
        "<br>": "\n",
        "<br/>": "\n",
        "<br />": "\n",
        "</p><p>": "\n\n",
        "</div><div>": "\n",
    }

    @classmethod
    def strip(cls, html: str) -> str:
        """
        Remove HTML tags and decode entities.
        
        Converts HTML to plain text suitable for LLM input.

        Args:
            html: HTML string to convert

        Returns:
            Plain text with tags removed and entities decoded
        """
        text = cls._remove_tags(html)
        text = cls._decode_entities(text)
        text = cls._convert_structures(text)
        text = cls._clean_whitespace(text)
        return text.strip()

    @staticmethod
    def _remove_tags(html: str) -> str:
        """Remove all HTML tags."""
        return re.sub(r"<[^>]+>", "", html)

    @classmethod
    def _decode_entities(cls, text: str) -> str:
        """Decode common HTML entities."""
        for entity, char in cls.HTML_ENTITIES.items():
            text = text.replace(entity, char)
        return text

    @classmethod
    def _convert_structures(cls, text: str) -> str:
        """Convert HTML structures to text equivalents."""
        for structure, replacement in cls.HTML_STRUCTURES.items():
            text = text.replace(structure, replacement)
        return text

    @staticmethod
    def _clean_whitespace(text: str) -> str:
        """Clean up excessive whitespace."""
        text = re.sub(r"\n\s+\n", "\n\n", text)
        text = re.sub(r" +", " ", text)
        return text


def strip_html_tags(html: str) -> str:
    """
    Remove HTML tags and decode entities.
    
    Convenience function wrapping HtmlStripper.strip().

    Args:
        html: HTML string to convert

    Returns:
        Plain text with tags removed and entities decoded
    """
    return HtmlStripper.strip(html)
