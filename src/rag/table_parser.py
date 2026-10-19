"""
Modular Table Parser & Linearizer for RAG Pipelines and API Gateways.

Provides robust parsing, extraction, and linearization of Markdown and JSON tables
into high-density semantic text formats optimized for vector search and LLM context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


def clean_cell_text(text: str, strip_markdown: bool = False) -> str:
    """Cleans cell text by trimming whitespace, handling escaped pipes, and optionally removing bold/italics."""
    text = text.replace("\\|", "|").strip()
    if strip_markdown:
        # Strip bold and italic markdown markers
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"\*([^*]+)\*", r"\1", text)
        text = re.sub(r"__([^_]+)__", r"\1", text)
        text = re.sub(r"_([^_]+)_", r"\1", text)
        text = re.sub(r"`([^`]+)`", r"\1", text)
    return text.strip()


@dataclass
class ParsedTable:
    """Represents a structured table extracted from Markdown, JSON, or an API payload."""
    headers: List[str]
    rows: List[List[str]]
    raw_markdown: str = ""
    title: Optional[str] = None
    start_char: int = -1
    end_char: int = -1
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> List[Dict[str, str]]:
        """Converts table rows into a list of dictionaries mapping header -> value."""
        records = []
        for row in self.rows:
            record = {}
            for idx, header in enumerate(self.headers):
                val = row[idx] if idx < len(row) else ""
                record[header] = clean_cell_text(val)
            records.append(record)
        return records

    def to_markdown(self) -> str:
        """Reconstructs a clean, standard Markdown table."""
        if not self.headers:
            return ""
        
        # Calculate column widths
        all_rows = [self.headers] + self.rows
        col_widths = []
        for col_idx in range(len(self.headers)):
            max_w = max(
                len(clean_cell_text(r[col_idx])) if col_idx < len(r) else 0 
                for r in all_rows
            )
            col_widths.append(max(max_w, 3))

        # Format header
        header_cells = [
            f" {self.headers[i].ljust(col_widths[i])} " 
            for i in range(len(self.headers))
        ]
        header_line = f"|{'|'.join(header_cells)}|"
        
        # Format separator
        sep_cells = [f":{'-' * (col_widths[i])}:" for i in range(len(self.headers))]
        sep_line = f"|{'|'.join(sep_cells)}|"

        # Format data rows
        row_lines = []
        for row in self.rows:
            cells = []
            for i in range(len(self.headers)):
                val = clean_cell_text(row[i]) if i < len(row) else ""
                cells.append(f" {val.ljust(col_widths[i])} ")
            row_lines.append(f"|{'|'.join(cells)}|")

        return "\n".join([header_line, sep_line] + row_lines)

    def to_narrative(self, format_style: str = "key_value", strip_markdown: bool = True) -> str:
        """Serializes the table into a high-semantic-density natural language block.
        
        Supported format_style:
            - 'key_value': "- Header1: Val1 | Header2: Val2 ..."
            - 'bulleted': "- Header1: Val1\n    Header2: Val2 ..."
            - 'sentence': "For Header1 'Val1', Header2 is 'Val2' ..."
        """
        lines = []
        prefix = f"[{self.title}]\n" if self.title else ""
        
        for row in self.rows:
            parts = []
            for idx, header in enumerate(self.headers):
                val = clean_cell_text(row[idx] if idx < len(row) else "", strip_markdown=strip_markdown)
                if not val or val.lower() in ("n/a", "none", "-"):
                    continue
                clean_h = clean_cell_text(header, strip_markdown=True)
                parts.append((clean_h, val))

            if not parts:
                continue

            if format_style == "key_value":
                line_str = " | ".join(f"{h}: {v}" for h, v in parts)
                lines.append(f"- {line_str}")
            elif format_style == "bulleted":
                first_h, first_v = parts[0]
                rest = "\n    ".join(f"{h}: {v}" for h, v in parts[1:])
                lines.append(f"- {first_h}: {first_v}\n    {rest}" if rest else f"- {first_h}: {first_v}")
            elif format_style == "sentence":
                lead_h, lead_v = parts[0]
                details = ", ".join(f"{h} is '{v}'" for h, v in parts[1:])
                lines.append(f"For {lead_h} '{lead_v}': {details}." if details else f"Entry for {lead_h}: '{lead_v}'.")
            else:
                line_str = " | ".join(f"{h}: {v}" for h, v in parts)
                lines.append(f"- {line_str}")

        return prefix + "\n".join(lines)

    def to_row_chunks(self, section: Optional[str] = None, strip_markdown: bool = True) -> List[str]:
        """Returns each row as a distinct, standalone semantic chunk with table & section context."""
        chunks = []
        context_label = section or self.title or "Table Record"
        
        for row in self.rows:
            parts = []
            for idx, header in enumerate(self.headers):
                val = clean_cell_text(row[idx] if idx < len(row) else "", strip_markdown=strip_markdown)
                if not val:
                    continue
                clean_h = clean_cell_text(header, strip_markdown=True)
                parts.append(f"{clean_h}: {val}")
            if parts:
                row_str = " | ".join(parts)
                chunks.append(f"[{context_label}] {row_str}")
        return chunks


class MarkdownTableParser:
    """Modular parser and transformer for Markdown tables.
    
    Can be used:
    1. During offline RAG ingestion to convert tables into rich semantic chunks.
    2. In an API gateway to parse, validate, and convert tabular user inputs.
    """

    TABLE_REGEX = re.compile(
        r'(?:^[ \t]*\|?[^\n\r|]+(?:\|[^\n\r|]+)+\|?[ \t]*\r?\n)'  # header row
        r'(?:^[ \t]*\|?(?:[ \t]*:?-+:?[ \t]*\|)+(?:[ \t]*:?-+:?[ \t]*)\|?[ \t]*\r?\n)'  # separator row
        r'(?:^[ \t]*\|?[^\n\r|]+(?:\|[^\n\r|]+)+\|?[ \t]*(?:\r?\n|$))+',  # 1+ data rows
        re.MULTILINE
    )

    @classmethod
    def split_row_cells(cls, line: str) -> List[str]:
        """Splits a single markdown table row line into stripped cell strings."""
        stripped = line.strip()
        if stripped.startswith("|"):
            stripped = stripped[1:]
        if stripped.endswith("|"):
            stripped = stripped[:-1]
        
        # Split on unescaped pipe
        cells = re.split(r"(?<!\\)\|", stripped)
        return [clean_cell_text(c) for c in cells]

    @classmethod
    def parse_single_table(cls, table_text: str, title: Optional[str] = None) -> Optional[ParsedTable]:
        """Parses a single raw Markdown table string into a ParsedTable."""
        lines = [line.strip() for line in table_text.strip().splitlines() if line.strip()]
        if len(lines) < 2:
            return None

        # Line 0 is header
        headers = cls.split_row_cells(lines[0])
        # Line 1 is delimiter/separator (e.g. |:---|:---|)
        # Lines 2+ are data rows
        rows = []
        for line in lines[2:]:
            # Skip divider lines if mistakenly present inside the body
            if re.match(r"^[ \t]*\|?(?:[ \t]*:?-+:?[ \t]*\|)+[ \t]*$", line):
                continue
            row_cells = cls.split_row_cells(line)
            # Ensure row matches headers length
            if len(row_cells) < len(headers):
                row_cells.extend([""] * (len(headers) - len(row_cells)))
            elif len(row_cells) > len(headers):
                row_cells = row_cells[:len(headers)]
            rows.append(row_cells)

        return ParsedTable(
            headers=headers,
            rows=rows,
            raw_markdown=table_text.strip(),
            title=title
        )

    @classmethod
    def extract_tables(cls, text: str) -> List[ParsedTable]:
        """Extracts and parses all Markdown tables found in text."""
        parsed_tables = []
        for match in cls.TABLE_REGEX.finditer(text):
            raw_table = match.group(0)
            start_pos = match.start()
            end_pos = match.end()

            # Attempt to find nearest preceding header as title
            preceding_text = text[:start_pos]
            headers = re.findall(r"^#{1,4}\s+(.*)$", preceding_text, re.MULTILINE)
            title = headers[-1].strip() if headers else None

            table = cls.parse_single_table(raw_table, title=title)
            if table:
                table.start_char = start_pos
                table.end_char = end_pos
                parsed_tables.append(table)

        return parsed_tables

    @classmethod
    def linearize_tables(
        cls,
        text: str,
        mode: str = "replace",
        format_style: str = "key_value",
        strip_markdown: bool = True
    ) -> str:
        """Transforms text by linearizing any Markdown tables found within it.
        
        Args:
            text: Markdown content containing tables.
            mode: 
                - 'replace': Replaces the raw table with the linearized text.
                - 'augment': Keeps the raw table and appends the linearized text underneath.
                - 'prepend': Prepends the linearized text above the raw table.
            format_style: 'key_value', 'bulleted', or 'sentence'.
            strip_markdown: Whether to remove bolding/italics in linearized output.
        """
        tables = cls.extract_tables(text)
        if not tables:
            return text

        # Replace in reverse order so character offsets stay valid
        transformed = text
        for table in reversed(tables):
            linearized = table.to_narrative(format_style=format_style, strip_markdown=strip_markdown)
            
            if mode == "replace":
                replacement = f"\n{linearized}\n"
            elif mode == "augment":
                replacement = f"\n{table.raw_markdown}\n\n*Table Summary:*\n{linearized}\n"
            elif mode == "prepend":
                replacement = f"\n*Table Summary:*\n{linearized}\n\n{table.raw_markdown}\n"
            else:
                replacement = f"\n{linearized}\n"

            transformed = transformed[:table.start_char] + replacement + transformed[table.end_char:]

        return transformed

    @classmethod
    def from_records(cls, records: List[Dict[str, Any]], title: Optional[str] = None) -> ParsedTable:
        """Constructs a ParsedTable from a list of dicts (e.g. from an API request or database query)."""
        if not records:
            return ParsedTable(headers=[], rows=[], title=title)

        # Collect ordered unique keys
        headers: List[str] = []
        for r in records:
            for k in r.keys():
                if k not in headers:
                    headers.append(k)

        rows: List[List[str]] = []
        for r in records:
            row = [str(r.get(h, "")) for h in headers]
            rows.append(row)

        table = ParsedTable(headers=headers, rows=rows, title=title)
        table.raw_markdown = table.to_markdown()
        return table

    @classmethod
    def linearize_records(
        cls,
        records: List[Dict[str, Any]],
        format_style: str = "key_value",
        title: Optional[str] = None
    ) -> str:
        """Helper to directly turn a list of dicts into high-density semantic text for RAG."""
        table = cls.from_records(records, title=title)
        return table.to_narrative(format_style=format_style)
