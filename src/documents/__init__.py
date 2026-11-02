"""Shared, lossless-source document parsing for generation and retrieval."""

from .parser import (
    DocumentBlock, DocumentParseError, ParsedDocument, UnsupportedDocumentError,
    context_blocks, parse_document, parse_document_text,
)

__all__ = ["DocumentBlock", "DocumentParseError", "ParsedDocument", "UnsupportedDocumentError",
           "context_blocks", "parse_document", "parse_document_text"]
