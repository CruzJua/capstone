import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.rag.table_parser import MarkdownTableParser, ParsedTable, clean_cell_text


def test_clean_cell_text():
    raw = "  **RED (Critical)** \\| Immediate  "
    cleaned = clean_cell_text(raw, strip_markdown=True)
    assert cleaned == "RED (Critical) | Immediate"


def test_parse_single_markdown_table():
    sample = """
| Name | Role | Department |
| :--- | :--- | :--- |
| Alice | Admin | IT |
| Bob | Support | Operations |
"""
    table = MarkdownTableParser.parse_single_table(sample, title="Staff Directory")
    assert table is not None
    assert table.headers == ["Name", "Role", "Department"]
    assert len(table.rows) == 2
    assert table.rows[0] == ["Alice", "Admin", "IT"]
    assert table.rows[1] == ["Bob", "Support", "Operations"]

    # Test to_dict conversion (crucial for API gateways)
    records = table.to_dict()
    assert len(records) == 2
    assert records[0] == {"Name": "Alice", "Role": "Admin", "Department": "IT"}
    assert records[1] == {"Name": "Bob", "Role": "Support", "Department": "Operations"}


def test_extract_tables_from_markdown_document():
    doc = """# Clinic Procedures

Here is the triage protocol:

| Category | Symptoms | Action |
| :--- | :--- | :--- |
| **RED** | Collapse | Treatment bay |
| **GREEN** | Limping | Regular exam |

And here is fee info:

| Code | Cost |
| :--- | :--- |
| VET-01 | $50 |
"""
    tables = MarkdownTableParser.extract_tables(doc)
    assert len(tables) == 2
    assert tables[0].headers == ["Category", "Symptoms", "Action"]
    assert tables[1].headers == ["Code", "Cost"]
    assert tables[0].title == "Clinic Procedures"


def test_linearize_tables_replace_and_augment():
    doc = """## Section 1
Before table.

| Col A | Col B |
| :--- | :--- |
| Val 1 | Val 2 |

After table."""
    replaced = MarkdownTableParser.linearize_tables(doc, mode="replace", format_style="key_value")
    assert "| Col A | Col B |" not in replaced
    assert "- Col A: Val 1 | Col B: Val 2" in replaced
    assert "Before table." in replaced
    assert "After table." in replaced

    augmented = MarkdownTableParser.linearize_tables(doc, mode="augment", format_style="key_value")
    assert "| Col A | Col B |" in augmented
    assert "- Col A: Val 1 | Col B: Val 2" in augmented


def test_from_records_and_records_to_markdown():
    records = [
        {"service": "Residential Clean", "rate": "$55/hr", "team": 1},
        {"service": "Commercial Janitorial", "rate": "$65/hr", "team": 2},
    ]
    table = MarkdownTableParser.from_records(records, title="Pricing Schedule")
    assert table.headers == ["service", "rate", "team"]
    assert len(table.rows) == 2
    
    md = table.to_markdown()
    assert "| service " in md
    assert "| Residential Clean " in md

    narrative = MarkdownTableParser.linearize_records(records, format_style="key_value")
    assert "- service: Residential Clean | rate: $55/hr | team: 1" in narrative


if __name__ == "__main__":
    test_clean_cell_text()
    test_parse_single_markdown_table()
    test_extract_tables_from_markdown_document()
    test_linearize_tables_replace_and_augment()
    test_from_records_and_records_to_markdown()
    print("All TableParser unit tests passed successfully!")
