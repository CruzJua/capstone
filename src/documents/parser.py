"""Parse source documents without tenant rules, semantic rewriting, or I/O side effects.

Raw source and its SHA-256 are retained. Markdown/text locators are Python
character offsets into raw_text; table metadata also traces any prepended
ancestor preambles as source_fragments. JSON locators are RFC 6901 pointers into
the decoded source. Structured rendering preserves values rather than claiming to
be a verbatim source quotation. Table blocks stay whole so headers, negative
columns, conditions, and row identities cannot become detached.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any


class DocumentParseError(ValueError):
    """The source cannot be parsed safely as the requested format."""


class UnsupportedDocumentError(DocumentParseError):
    """The requested source format is unsupported."""


@dataclass(frozen=True)
class DocumentBlock:
    text: str
    kind: str
    section: str
    locator: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedDocument:
    source_id: str
    sha256: str
    raw_text: str
    blocks: list[DocumentBlock]


def _span(start: int, end: int) -> dict[str, int]:
    return {"start": start, "end": end}


def _cells(line: str) -> list[str]:
    """Split actual unescaped pipes, preserving cell text and empty columns."""
    line = line.strip()
    boundaries = []
    for index, character in enumerate(line):
        if character != "|":
            continue
        backslashes = 0
        cursor = index - 1
        while cursor >= 0 and line[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2 == 0:
            boundaries.append(index)
    if not boundaries:
        return [line]
    pieces = []
    start = 0
    for boundary in boundaries:
        pieces.append(line[start:boundary].strip())
        start = boundary + 1
    pieces.append(line[start:].strip())
    if boundaries[0] == 0:
        pieces.pop(0)
    if boundaries[-1] == len(line) - 1:
        pieces.pop()
    return pieces


def _paragraphs(text: str, start: int = 0, end: int | None = None,
                section: str = "", metadata: dict | None = None) -> list[DocumentBlock]:
    end = len(text) if end is None else end
    blocks = []
    for match in re.finditer(r"\S[\s\S]*?(?=\r?\n[ \t]*\r?\n|\Z)", text[start:end]):
        left, right = start + match.start(), start + match.end()
        blocks.append(DocumentBlock(text[left:right], "paragraph", section, _span(left, right),
                                    dict(metadata or {})))
    return blocks


def _footer_end(lines: list[str], start: int) -> int:
    """Retain following section prose conservatively, without interpreting it.

    Footnotes and conditions after a table can constrain its rows. Stop at the
    next heading or table; the parser does not certify semantic applicability.
    """
    fence = None
    for index in range(start, len(lines)):
        line = lines[index]
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence is not None:
            continue
        if re.match(r"^ {0,3}#{1,6}[ \t]+", line):
            return index
        if index + 1 < len(lines):
            if line.strip() and re.fullmatch(r" {0,3}(=+|-+)[ \t]*(?:\r?\n)?", lines[index + 1]):
                return index
            headers, separators = _cells(line), _cells(lines[index + 1])
            if len(headers) > 1 and len(headers) == len(separators) and all(
                    re.fullmatch(r":?-{3,}:?", cell) for cell in separators):
                return index
    return len(lines)


def _markdown(text: str) -> list[DocumentBlock]:
    lines = text.splitlines(keepends=True)
    offsets = []
    offset = 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)
    offsets.append(len(text))
    blocks = []
    headings: list[tuple[int, str]] = []
    scopes: list[dict[str, Any]] = []
    first_heading_start = None
    section_start = 0
    pending_start = 0
    fence = None
    index = 0
    while index < len(lines):
        line = lines[index]
        fence_match = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if fence_match:
            marker = fence_match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            index += 1
            continue
        if fence is not None:
            index += 1
            continue
        heading = re.match(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*(?:\r?\n)?$", line)
        setext = index + 1 < len(lines) and line.strip() and re.fullmatch(
            r" {0,3}(=+|-+)[ \t]*(?:\r?\n)?", lines[index + 1])
        if heading or setext:
            if first_heading_start is None:
                first_heading_start = offsets[index]
            section = " / ".join(value for _, value in headings)
            blocks.extend(_paragraphs(text, pending_start, offsets[index], section,
                                      {"heading_path": [value for _, value in headings]}))
            level = len(heading.group(1)) if heading else (1 if lines[index + 1].lstrip().startswith("=") else 2)
            title = heading.group(2) if heading else line.strip()
            scopes = [scope for scope in scopes if scope["level"] < level]
            for scope in scopes:
                if scope["preamble_end"] is None:
                    scope["preamble_end"] = offsets[index]
            scopes.append({"level": level, "start": offsets[index], "preamble_end": None})
            headings = [(depth, value) for depth, value in headings if depth < level] + [(level, title)]
            stop = index + (1 if heading else 2)
            section_start = offsets[index]
            blocks.append(DocumentBlock(text[offsets[index]:offsets[stop]], "heading",
                                        " / ".join(value for _, value in headings),
                                        _span(offsets[index], offsets[stop]),
                                        {"heading_path": [value for _, value in headings], "level": level}))
            pending_start = offsets[stop]
            index = stop
            continue
        if index + 1 < len(lines) and "|" in line:
            headers = _cells(line)
            separators = _cells(lines[index + 1])
            is_table = len(headers) > 1 and len(headers) == len(separators) and all(
                re.fullmatch(r":?-{3,}:?", cell) for cell in separators)
            if is_table:
                section = " / ".join(value for _, value in headings)
                blocks.extend(_paragraphs(text, pending_start, offsets[index], section,
                                          {"heading_path": [value for _, value in headings]}))
                stop = index + 2
                rows = []
                while stop < len(lines) and lines[stop].strip() and "|" in lines[stop]:
                    cells = _cells(lines[stop])
                    if len(cells) != len(headers):
                        raise DocumentParseError(f"Markdown table row has {len(cells)} cells; expected {len(headers)}")
                    rows.append({"index": len(rows), "cells": cells,
                                 "locator": _span(offsets[stop], offsets[stop + 1])})
                    stop += 1
                # Include the original section prefix, which may contain
                # conditions applying to every row. This intentional overlap
                # is disclosed by the separate table_locator.
                context_start = section_start
                footer_stop = _footer_end(lines, stop)
                fragments = ([_span(0, first_heading_start)]
                             if first_heading_start and text[:first_heading_start].strip() else [])
                fragments.extend(_span(scope["start"], scope["preamble_end"]) for scope in scopes[:-1])
                fragments.append(_span(context_start, offsets[footer_stop]))
                block_text = "\n".join(text[span["start"]:span["end"]] for span in fragments)
                blocks.append(DocumentBlock(block_text, "table", section,
                                            _span(context_start, offsets[stop]), {
                                                "context_role": "table", "heading_path": [v for _, v in headings],
                                                "headers": headers, "rows": rows,
                                                "table_locator": _span(offsets[index], offsets[stop]),
                                                "header_locator": _span(offsets[index], offsets[index + 1]),
                                                "separator_locator": _span(offsets[index + 1], offsets[index + 2]),
                                                "context_locator": _span(context_start, offsets[index]),
                                                "context_after_locator": _span(offsets[stop], offsets[footer_stop]),
                                                "source_fragments": fragments,
                                                "rendering": "verbatim_source_fragments",
                                            }))
                pending_start = offsets[stop]
                index = stop
                continue
        index += 1
    blocks.extend(_paragraphs(text, pending_start, len(text), " / ".join(v for _, v in headings),
                              {"heading_path": [v for _, v in headings]}))
    return blocks


def _pointer_part(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _json_render(value: Any, depth: int = 0) -> str:
    """Render exact decimal values without converting through binary floats."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (dict, list)) and value:
        indent = " " * (4 * (depth + 1))
        if isinstance(value, dict):
            parts = [json.dumps(k, ensure_ascii=False) + ": " + _json_render(v, depth + 1)
                     for k, v in value.items()]
            left, right = "{", "}"
        else:
            parts = [_json_render(item, depth + 1) for item in value]
            left, right = "[", "]"
        return left + "\n" + indent + (",\n" + indent).join(parts) + "\n" + " " * (4 * depth) + right
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _metadata_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _metadata_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_metadata_value(item) for item in value]
    return value


def _json_blocks(node: Any, pointer: str = "", context: list | None = None) -> list[DocumentBlock]:
    context = list(context or [])
    if isinstance(node, list) and node and all(isinstance(item, (dict, list)) for item in node):
        return [block for index, item in enumerate(node)
                for block in _json_blocks(item, f"{pointer}/{index}", context)]
    if isinstance(node, dict):
        arrays = [(key, value) for key, value in node.items() if isinstance(value, list) and value
                  and all(isinstance(item, (dict, list)) for item in value)]
        if arrays:
            blocks = []
            for key, value in arrays:
                parent = {k: v for k, v in node.items() if k != key}
                ancestry = context + ([{"pointer": pointer, "fields": parent}] if parent else [])
                blocks.extend(_json_blocks(value, f"{pointer}/{_pointer_part(key)}", ancestry))
            return blocks
    rendered = {"parent_context": context, "record": node} if context else node
    return [DocumentBlock(_json_render(rendered),
                          "json_record", pointer, {"pointer": pointer},
                          {"parent_context": _metadata_value(context), "value": _metadata_value(node),
                           "rendering": "structural_json", "numeric_metadata_encoding": "decimal_strings"})]


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise DocumentParseError("JSON object contains a duplicate key")
        result[key] = value
    return result


def parse_document_text(source_id: str, text: str, suffix: str) -> ParsedDocument:
    """Parse text; hashes its exact UTF-8 encoding without normalizing newlines."""
    if not isinstance(source_id, str) or not source_id.strip():
        raise DocumentParseError("source_id must be a non-empty string")
    if not isinstance(text, str):
        raise DocumentParseError("document text must be a string")
    if not isinstance(suffix, str) or not suffix:
        raise UnsupportedDocumentError("Document suffix must be a non-empty string")
    suffix = suffix.lower()
    if not suffix.startswith("."):
        suffix = "." + suffix
    if suffix == ".md":
        blocks = _markdown(text)
    elif suffix == ".txt":
        blocks = _paragraphs(text)
    elif suffix == ".json":
        try:
            def reject_constant(value):
                raise DocumentParseError("JSON contains a non-finite numeric constant")
            node = json.loads(text, object_pairs_hook=_unique_object, parse_constant=reject_constant,
                              parse_float=Decimal)
        except json.JSONDecodeError as exc:
            raise DocumentParseError(f"Malformed JSON at line {exc.lineno}, column {exc.colno}") from exc
        blocks = _json_blocks(node)
    else:
        raise UnsupportedDocumentError(f"Unsupported document suffix: {suffix}")
    return ParsedDocument(source_id, hashlib.sha256(text.encode("utf-8")).hexdigest(), text, blocks)


def parse_document(path: Path, source_id: str | None = None) -> ParsedDocument:
    """Read UTF-8 bytes exactly; the default source identity is the filename."""
    path = Path(path)
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DocumentParseError("Document is not UTF-8 text") from exc
    return parse_document_text(path.name if source_id is None else source_id, text, path.suffix)


def context_blocks(document: ParsedDocument, max_words: int) -> list[DocumentBlock]:
    """Pack context by complete structural units, never by clipping their text.

    Tables exceeding the budget split only at row boundaries. Every row repeats
    full column headers, inherited preambles, and following section prose. A
    paragraph, JSON record, or single fully contextualized row that cannot fit
    fails explicitly. Arbitrary keyed JSON objects cannot safely be classified
    as records versus policy constraints without a schema, so they stay atomic.
    """
    if type(max_words) is not int or max_words < 1:
        raise DocumentParseError("max_words must be a positive integer")
    result = []
    for block in document.blocks:
        if len(block.text.split()) <= max_words:
            result.append(block)
            continue
        if block.kind != "table" or not block.metadata.get("rows"):
            raise DocumentParseError(
                f"Atomic {block.kind} block in {document.source_id} exceeds {max_words} words; "
                "increase the context budget rather than truncate source content"
            )
        metadata = block.metadata
        # All inherited preambles precede the final current-section fragment.
        inherited = list(metadata.get("source_fragments", []))[:-1]
        before = metadata["context_locator"]
        after = metadata["context_after_locator"]
        header = _span(metadata["header_locator"]["start"], metadata["separator_locator"]["end"])
        for row in metadata["rows"]:
            fragments = [span for span in [*inherited, before, header, row["locator"], after]
                         if span["start"] < span["end"]]
            rendered = "\n".join(document.raw_text[span["start"]:span["end"]] for span in fragments)
            if len(rendered.split()) > max_words:
                raise DocumentParseError(
                    f"Atomic contextualized table row {row['index']} in {document.source_id} "
                    f"exceeds {max_words} words; no row or qualifying context was truncated"
                )
            result.append(DocumentBlock(rendered, "table_row", block.section, dict(row["locator"]), {
                **metadata, "rows": [row], "row_index": row["index"],
                "source_fragments": fragments, "parent_block_locator": dict(block.locator),
                "context_word_budget": max_words,
            }))
    return result
