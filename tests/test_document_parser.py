"""Synthetic, tenant-independent checks for the shared source parser."""

import hashlib
import json
import tempfile
import unittest
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from src.documents.parser import (
    DocumentParseError, UnsupportedDocumentError, context_blocks, parse_document, parse_document_text,
)


class DocumentParserTests(unittest.TestCase):
    def test_markdown_table_retains_negatives_blank_cells_units_and_context(self):
        text = ("# Safety\n\nOnly when condition A holds; otherwise do not proceed.\n\n"
                "| Identity | Do Not | Quantity | Exception |\n"
                "| --- | :--- | ---: | --- |\n"
                "| item-1 | Never apply heat | 3–5 mg/kg | Unless authorized |\n"
                "| item-2 | None | | Not before 48 hours |\n")
        parsed = parse_document_text("unseen_source", text, ".md")
        table = next(block for block in parsed.blocks if block.kind == "table")
        self.assertEqual(table.text, text[table.locator["start"]:table.locator["end"]])
        self.assertIn("Only when condition A holds; otherwise do not proceed.", table.text)
        self.assertEqual(table.metadata["headers"], ["Identity", "Do Not", "Quantity", "Exception"])
        self.assertEqual(table.metadata["rows"][1]["cells"], ["item-2", "None", "", "Not before 48 hours"])
        self.assertIn("3–5 mg/kg", table.text)
        self.assertIn("Unless authorized", table.text)
        self.assertEqual(table.section, "Safety")
        row_span = table.metadata["rows"][0]["locator"]
        self.assertTrue(text[row_span["start"]:row_span["end"]].startswith("| item-1"))

    def test_escaped_pipes_and_backslash_parity_preserve_column_association(self):
        text = "| Key | Meaning |\n| --- | --- |\n| a | Left \\| right |\n| b\\\\ | next |\n"
        table = next(b for b in parse_document_text("any", text, "md").blocks if b.kind == "table")
        self.assertEqual(table.metadata["rows"][0]["cells"], ["a", "Left \\| right"])
        self.assertEqual(table.metadata["rows"][1]["cells"], ["b\\\\", "next"])

    def test_malformed_table_never_silently_truncates_extra_cells(self):
        with self.assertRaisesRegex(DocumentParseError, "3 cells; expected 2"):
            parse_document_text("any", "| A | B |\n| --- | --- |\n| 1 | 2 | 3 |\n", ".md")

    def test_nested_and_setext_headings_keep_scope_without_parsing_code_as_tables(self):
        text = "Main\n====\n\n## Child\n\nNot permitted.\n\n```md\n# Fake\n| A | B |\n| --- | --- |\n| x | y |\n```\n"
        parsed = parse_document_text("any", text, ".md")
        self.assertFalse(any(b.kind == "table" for b in parsed.blocks))
        self.assertEqual([b.section for b in parsed.blocks if b.kind == "heading"], ["Main", "Main / Child"])
        self.assertIn("# Fake", parsed.blocks[-1].text)

    def test_table_inherits_parent_qualifiers_without_inheriting_previous_sibling_section(self):
        text = ("# Parent\n\nNever use without authorization.\n\n## Sibling\n\nSibling-only information.\n\n"
                "## Target\n\nOnly after 48 hours.\n\n| Item | Do Not |\n| --- | --- |\n| X | Exceed 5 mg |\n")
        table = next(b for b in parse_document_text("any", text, ".md").blocks if b.kind == "table")
        self.assertIn("Never use without authorization.", table.text)
        self.assertIn("Only after 48 hours.", table.text)
        self.assertNotIn("Sibling-only information.", table.text)
        self.assertEqual(table.text, "\n".join(text[span["start"]:span["end"]]
                                              for span in table.metadata["source_fragments"]))

    def test_json_records_keep_keys_nested_values_and_parent_conditions(self):
        text = json.dumps({"policy": "Never operate below -5 C unless authorized", "records": [
            {"id": "r1", "details": {"quantity": "2–4 kg", "Do Not": "Do not mix"}},
            {"id": "r2", "exceptions": ["not at night", "only after inspection"]},
        ]})
        parsed = parse_document_text("new_json", text, ".json")
        self.assertEqual([b.locator["pointer"] for b in parsed.blocks], ["/records/0", "/records/1"])
        for block in parsed.blocks:
            rendered = json.loads(block.text)
            self.assertEqual(rendered["parent_context"][0]["fields"]["policy"],
                             "Never operate below -5 C unless authorized")
        self.assertEqual(json.loads(parsed.blocks[0].text)["record"]["details"]["Do Not"], "Do not mix")
        self.assertEqual(json.loads(parsed.blocks[1].text)["record"]["exceptions"],
                         ["not at night", "only after inspection"])

    def test_json_keyed_records_are_not_flattened_into_orphan_values(self):
        value = {"A": {"answer": "Do not do this", "condition": "unless approved"},
                 "B": {"answer": "Wait 10–14 days", "followup": {"units": "days"}}}
        block = parse_document_text("arbitrary", json.dumps(value), "json").blocks[0]
        self.assertEqual(json.loads(block.text), value)
        self.assertEqual(block.locator, {"pointer": ""})

    def test_json_pointer_escaping_and_exact_decimal_values(self):
        parsed = parse_document_text("arbitrary", '{"a/b~c":[{"amount":1234567890.1234567890123456789}]}', ".json")
        block = parsed.blocks[0]
        self.assertEqual(block.locator["pointer"], "/a~1b~0c/0")
        self.assertEqual(json.loads(block.text, parse_float=Decimal)["amount"], Decimal("1234567890.1234567890123456789"))
        json.dumps(asdict(parsed), allow_nan=False)  # Metadata stays JSON serializable.

    def test_invalid_json_duplicates_and_nonfinite_constants_are_explicit_errors(self):
        for text in ('{"unfinished":', '{"same":1,"same":2}', '{"number":NaN}', '{"number":Infinity}'):
            with self.subTest(text=text), self.assertRaises(DocumentParseError):
                parse_document_text("any", text, ".json")

    def test_txt_paragraphs_retain_verbatim_character_spans(self):
        text = "Do not replace 2.5 mg with 25 mg.\r\nUnless authorized, wait.\r\n\r\nSecond paragraph: never.\r\n"
        parsed = parse_document_text("plain", text, ".txt")
        self.assertEqual(len(parsed.blocks), 2)
        for block in parsed.blocks:
            self.assertEqual(block.text, text[block.locator["start"]:block.locator["end"]])
        self.assertIn("\r\nUnless authorized", parsed.blocks[0].text)

    def test_read_hashes_raw_bytes_and_is_independent_of_renamed_unseen_path(self):
        raw = "# Unseen\r\n\r\nDo not remove 7–9 mm.\r\n".encode()
        with tempfile.TemporaryDirectory() as temporary:
            original, renamed = Path(temporary) / "unseen.md", Path(temporary) / "renamed.MD"
            original.write_bytes(raw)
            renamed.write_bytes(raw)
            a, b = parse_document(original), parse_document(renamed)
            self.assertEqual(a.sha256, hashlib.sha256(raw).hexdigest())
            self.assertEqual(a.sha256, b.sha256)
            self.assertEqual(a.blocks, b.blocks)
            self.assertEqual(a.raw_text.encode(), raw)
            self.assertEqual(parse_document(renamed, "stable-id").source_id, "stable-id")

    def test_default_source_identity_keeps_extensions_distinct(self):
        with tempfile.TemporaryDirectory() as temporary:
            markdown, structured = Path(temporary) / "policy.md", Path(temporary) / "policy.json"
            markdown.write_text("# Policy\nNever omit the suffix.")
            structured.write_text('{"policy":"Never omit the suffix."}')
            self.assertEqual(parse_document(markdown).source_id, "policy.md")
            self.assertEqual(parse_document(structured).source_id, "policy.json")

    def test_unsupported_binary_and_empty_documents_are_explicit(self):
        with self.assertRaises(UnsupportedDocumentError):
            parse_document_text("any", "data", ".pdf")
        with self.assertRaises(DocumentParseError):
            parse_document_text("", "data", ".txt")
        self.assertEqual(parse_document_text("empty", "", ".txt").blocks, [])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.txt"
            path.write_bytes(b"\xff\xfe")
            with self.assertRaisesRegex(DocumentParseError, "not UTF-8"):
                parse_document(path)

    def test_large_table_packs_full_rows_with_headers_negatives_qualifiers_and_trace(self):
        rows = [f"| item-{i} | Do not exceed {i + 1} mg/kg | Only after authorization |\n" for i in range(25)]
        text = ("# Policy\n\nNever use without inspection.\n\n## Schedule\n\n"
                "| Identity | Do Not | Condition |\n| --- | --- | --- |\n" + "".join(rows)
                + "\n* All rows require follow-up within 48 hours unless authorized otherwise.\n")
        parsed = parse_document_text("unseen", text, ".md")
        packed = context_blocks(parsed, 80)
        tables = [b for b in packed if b.kind == "table_row"]
        self.assertEqual(len(tables), 25)
        for index, block in enumerate(tables):
            self.assertLessEqual(len(block.text.split()), 80)
            self.assertIn(rows[index], block.text)
            self.assertIn("| Identity | Do Not | Condition |", block.text)
            self.assertIn("| --- | --- | --- |", block.text)
            self.assertIn("Never use without inspection.", block.text)
            self.assertIn("All rows require follow-up within 48 hours unless authorized otherwise.", block.text)
            self.assertEqual(block.metadata["row_index"], index)
            self.assertEqual(block.text, "\n".join(text[s["start"]:s["end"]]
                                                   for s in block.metadata["source_fragments"]))
            self.assertEqual(text[block.locator["start"]:block.locator["end"]], rows[index])
            self.assertEqual(len(block.metadata["rows"]), 1)

    def test_atomic_oversize_never_clips_paragraph_json_or_single_table_row(self):
        paragraph = parse_document_text("plain", "Never omit " + "qualifier " * 100, ".txt")
        json_record = parse_document_text("record", json.dumps({"condition": "Never omit " + "word " * 100}), ".json")
        table = parse_document_text("table", "| ID | Do Not |\n| --- | --- |\n| X | " + "word " * 100 + "|\n", ".md")
        for parsed in (paragraph, json_record, table):
            original = asdict(parsed)
            with self.subTest(source=parsed.source_id), self.assertRaises(DocumentParseError):
                context_blocks(parsed, 30)
            self.assertEqual(asdict(parsed), original)

    def test_context_budget_validation_and_small_block_identity(self):
        parsed = parse_document_text("small", "Do not change this.", ".txt")
        self.assertIs(context_blocks(parsed, 20)[0], parsed.blocks[0])
        for budget in (0, -1, True, 2.5):
            with self.subTest(budget=budget), self.assertRaises(DocumentParseError):
                context_blocks(parsed, budget)


if __name__ == "__main__":
    unittest.main()
