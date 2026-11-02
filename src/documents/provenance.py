"""Conservative, source-aware evidence provenance checks.

Finding a quoted span establishes where text came from, never whether an answer
is correct. Cross-source matches are review/quarantine findings, not permission
to relabel a training target. No model, database, or network calls are made.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from src.documents.parser import DocumentBlock, ParsedDocument
from src.documents.integration import context_blocks, load_documents


_NEGATIVE = re.compile(r"\b(?:do\s+not|must\s+not|never|prohibited|forbidden|not\s+allowed|cannot)\b", re.I)
_EMPHASIS = re.compile(r"(?<!\w)(\*\*|__|`)(?=\S)(.+?)(?<=\S)\1(?!\w)", re.S)
_LIMITATION = (
    "A verified quote establishes provenance only, not semantic correctness, answer "
    "completeness, routing, or a safe training target. Unmatched quotations can be "
    "paraphrases; context and ambiguity findings require review. No source labels, "
    "answers, rationales, datasets, or benchmark files are changed."
)


@dataclass(frozen=True)
class NormalizedText:
    text: str
    original_positions: tuple[int, ...]
    operations: tuple[str, ...]


def normalize_structural(text: str) -> NormalizedText:
    """Collapse whitespace and remove balanced markup; preserve all claim tokens.

    Case, punctuation, digits, units, negatives, comparison operators, qualifiers,
    and table separators are preserved. No stemming, fuzzy matching, Unicode
    compatibility folding, number conversion, or word deletion is performed.
    Character positions map the normalized span back to its input surface.
    """
    positions = list(range(len(text)))
    operations = []
    matches = list(_EMPHASIS.finditer(text))
    if matches:
        remove = set()
        for match in matches:
            size = len(match.group(1))
            remove.update(range(match.start(), match.start() + size))
            remove.update(range(match.end() - size, match.end()))
        positions = [position for position in positions if position not in remove]
        text = "".join(text[position] for position in positions)
        operations.append("remove_balanced_markdown_emphasis_or_code_delimiters")
    chars, mapped = [], []
    for index, char in enumerate(text):
        if char.isspace():
            if chars and chars[-1] != " ":
                chars.append(" ")
                mapped.append(positions[index])
        else:
            chars.append(char)
            mapped.append(positions[index])
    if chars and chars[-1] == " ":
        chars.pop()
        mapped.pop()
    normalized = "".join(chars)
    if normalized != text:
        operations.append("collapse_whitespace_and_trim")
    return NormalizedText(normalized, tuple(mapped), tuple(operations))


def _pointer_token(token: object) -> str:
    return str(token).replace("~", "~0").replace("/", "~1")


def _json_strings(value: object, pointer: str = ""):
    if isinstance(value, str):
        yield pointer, value
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _json_strings(child, pointer + "/" + str(index))
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _json_strings(child, pointer + "/" + _pointer_token(key))


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Evidence JSON contains a duplicate key")
        result[key] = value
    return result


def _spans(text: str, quote: str) -> list[tuple[int, int]]:
    result, start = [], 0
    while (index := text.find(quote, start)) >= 0:
        result.append((index, index + len(quote)))
        start = index + 1
    return result


def _block_description(block: DocumentBlock, *, include_text: bool = False) -> dict:
    result = {
        "kind": block.kind, "section": block.section, "locator": block.locator,
        "canonical_text_sha256": hashlib.sha256(block.text.encode()).hexdigest(),
    }
    if block.metadata.get("source_fragments"):
        result["source_fragments"] = block.metadata["source_fragments"]
    if include_text:
        result["text"] = block.text
    return result


def _containing_blocks(document: ParsedDocument, locator: dict) -> list[DocumentBlock]:
    candidates = []
    for block in document.blocks:
        if "pointer" in locator and "pointer" in block.locator:
            pointer, parent = locator["pointer"], block.locator["pointer"]
            if pointer == parent or pointer.startswith(parent + "/") or parent == "":
                candidates.append(block)
        elif "start" in locator and "start" in block.locator:
            if block.locator["start"] <= locator["start"] and locator["end"] <= block.locator["end"]:
                candidates.append(block)
    if "pointer" in locator:
        candidates.sort(key=lambda block: -len(block.locator.get("pointer", "")))
    else:
        candidates.sort(key=lambda block: block.locator.get("end", 0) - block.locator.get("start", 0))
    return candidates


@dataclass
class _Surface:
    text: str
    kind: str
    locator: dict
    normalized: NormalizedText
    block: DocumentBlock | None = None


class EvidenceProvenanceValidator:
    """Index one explicit tenant corpus once, then validate many evidence lists."""

    def __init__(self, corpus: dict[str, ParsedDocument]):
        self.corpus = corpus
        self.surfaces = {}
        self.projection_diagnostics = []
        for source, document in corpus.items():
            if not isinstance(source, str) or not source or source != document.source_id:
                raise ValueError("Corpus keys must equal exact ParsedDocument.source_id values")
            primary = []
            if Path(source).suffix.lower() == ".json":
                try:
                    primary = [_Surface(text, "decoded_json_value", {"pointer": pointer}, normalize_structural(text))
                               for pointer, text in _json_strings(json.loads(document.raw_text))]
                except json.JSONDecodeError:
                    pass
            if not primary:
                primary = [_Surface(document.raw_text, "raw_verbatim", {"start": 0, "end": len(document.raw_text)},
                                    normalize_structural(document.raw_text))]
            blocks = [_Surface(block.text, "parsed_block_span", block.locator,
                               normalize_structural(block.text), block) for block in document.blocks]
            contextual_rows = []
            for block in document.blocks:
                if block.kind != "table" or len(block.text.split()) <= 500:
                    continue
                try:
                    projection = context_blocks(ParsedDocument(
                        document.source_id, document.sha256, document.raw_text, [block]), 500)
                except ValueError as exc:
                    self.projection_diagnostics.append({
                        "source": source, "source_sha256": document.sha256,
                        "locator": block.locator, "derived_projection_unavailable": str(exc),
                        "raw_and_full_block_validation_available": True,
                    })
                    continue
                contextual_rows.extend(
                    _Surface(row.text, "parsed_block_span", row.locator, normalize_structural(row.text), row)
                    for row in projection if row.kind == "table_row"
                )
            self.surfaces[source] = (primary, blocks, contextual_rows)

    def _matches(self, source: str, quote: str, normalized_quote: NormalizedText) -> list[dict]:
        document = self.corpus[source]
        primary, blocks, contextual_rows = self.surfaces[source]
        # Prefer actual raw/decoded source spans; do not count the same occurrence
        # again merely because a canonical block repeats it with contextual labels.
        for surfaces, structural in ((primary, False), (primary, True), (contextual_rows, False),
                                     (blocks, False), (contextual_rows, True), (blocks, True)):
            found = []
            for surface in surfaces:
                haystack = surface.normalized.text if structural else surface.text
                needle = normalized_quote.text if structural else quote
                for start, end in _spans(haystack, needle):
                    if structural:
                        original_start = surface.normalized.original_positions[start]
                        original_end = surface.normalized.original_positions[end - 1] + 1
                    else:
                        original_start, original_end = start, end
                    locator = dict(surface.locator)
                    if surface.kind == "raw_verbatim":
                        locator = {"start": original_start, "end": original_end}
                    containing = [surface.block] if surface.block else _containing_blocks(document, locator)
                    trace = []
                    if surface.kind == "decoded_json_value":
                        trace.append("json_string_decoding_at_rfc6901_pointer")
                    if surface.kind == "parsed_block_span":
                        trace.append("shared_document_parser_canonical_block_projection")
                        if surface.block and surface.block.kind == "table_row":
                            trace.append("contextual_table_row_projection_500_word_budget")
                    if structural:
                        trace.extend("source:" + operation for operation in surface.normalized.operations)
                        trace.extend("quote:" + operation for operation in normalized_quote.operations)
                    found.append({
                        "source": source, "source_sha256": document.sha256,
                        "match_kind": surface.kind, "comparison": "structural" if structural else "exact",
                        "locator": locator, "surface_span": {"start": original_start, "end": original_end},
                        "transform_trace": trace,
                        "blocks": [_block_description(block) for block in containing],
                        "_containing": containing,
                    })
            if found:
                return found
        return []

    @staticmethod
    def _finding(code: str, classification: str, detail: str) -> dict:
        return {"code": code, "classification": classification, "detail": detail}

    def _context_findings(self, matches: list[dict], quote: str) -> tuple[list[dict], list[dict]]:
        findings, suggestions, seen_blocks = [], [], set()
        normalized_quote = normalize_structural(quote).text
        for match in matches:
            for block in match["_containing"]:
                block_key = json.dumps(block.locator, sort_keys=True)
                if block_key in seen_blocks:
                    continue
                seen_blocks.add(block_key)
                findings_before = len(findings)
                metadata = block.metadata or {}
                table_locator = metadata.get("table_locator")
                table_match = block.kind in {"table", "table_row"}
                if table_match and table_locator and "start" in match["locator"]:
                    table_match = (match["locator"]["start"] < table_locator["end"]
                                   and match["locator"]["end"] > table_locator["start"])
                headers = metadata.get("headers") or []
                if table_match and headers:
                    missing = [str(header) for header in headers
                               if normalize_structural(str(header)).text not in normalized_quote]
                    if missing:
                        findings.append(self._finding(
                            "table_header_missing", "review_flag",
                            "Quote intersects a table but omits header context: " + "; ".join(missing),
                        ))
                headings = metadata.get("heading_path") or []
                context_parts = [str(block.section or ""), *map(str, headings)]
                if table_match:
                    context_parts.extend(map(str, headers))
                if table_match and table_locator:
                    raw = self.corpus[match["source"]].raw_text
                    for fragment in metadata.get("source_fragments") or [block.locator]:
                        if "start" in fragment and fragment["start"] < table_locator["start"]:
                            context_parts.append(raw[fragment["start"]:min(fragment["end"], table_locator["start"])])
                        if "end" in fragment and fragment["end"] > table_locator["end"]:
                            context_parts.append(raw[max(fragment["start"], table_locator["end"]):fragment["end"]])
                context = "\n".join(context_parts)
                negatives = [matched.group(0) for matched in _NEGATIVE.finditer(context)]
                omitted_negatives = [negative for negative in negatives
                                     if negative.casefold() not in normalized_quote.casefold()]
                if omitted_negatives:
                    findings.append(self._finding(
                        "negative_context_missing", "review_flag",
                        "Containing heading/header has restrictive language omitted by the quote: "
                        + "; ".join(dict.fromkeys(omitted_negatives)),
                    ))
                if len(findings) > findings_before:
                    suggestions.append(_block_description(block, include_text=True))
        # Several nested blocks can expose the same context warning.
        unique = {json.dumps(item, sort_keys=True): item for item in findings}
        return list(unique.values()), suggestions

    def validate_evidence(self, evidence: object) -> dict:
        """Return JSON-serializable provenance findings; never repair source/target text."""
        if not isinstance(evidence, list):
            evidence = [None]
        items = []
        for index, entry in enumerate(evidence):
            item = {"index": index, "claimed_source": None, "quote": None, "status": "invalid_schema",
                    "provenance_verified": False, "findings": [], "matches": [], "suggested_blocks": []}
            items.append(item)
            if (not isinstance(entry, dict) or set(entry) != {"source", "quote"}
                    or not isinstance(entry.get("source"), str) or not entry["source"].strip()
                    or not isinstance(entry.get("quote"), str) or not entry["quote"].strip()):
                item["findings"].append(self._finding(
                    "schema_invalid", "schema_error", "Evidence must contain exactly nonempty string source and quote fields."
                ))
                continue
            source, quote = entry["source"], entry["quote"]
            item.update(claimed_source=source, quote=quote)
            normalized = normalize_structural(quote)
            if not normalized.text:
                item["findings"].append(self._finding("schema_invalid", "schema_error", "Quote has no content after formatting normalization."))
                continue
            all_matches = {name: matches for name in self.corpus
                           if (matches := self._matches(name, quote, normalized))}
            claimed = all_matches.get(source, [])
            if source not in self.corpus:
                item["status"] = "unknown_source"
                item["findings"].append(self._finding(
                    "unknown_source", "confirmed_provenance_failure", "Claimed source ID is absent from the supplied tenant corpus."
                ))
            elif not claimed and all_matches:
                item["status"] = "source_mismatch"
                item["findings"].append(self._finding(
                    "source_mismatch", "confirmed_provenance_failure",
                    "Quote matches a different source and not its claimed source. Review; do not automatically relabel."
                ))
            elif not claimed:
                item["status"] = "unmatched"
                item["findings"].append(self._finding(
                    "quote_unmatched", "review_flag", "No conservative source match. It may be a paraphrase or unsupported; semantics were not assessed."
                ))
            else:
                item["provenance_verified"] = True
                item["status"] = "verified_structural" if claimed[0]["comparison"] == "structural" else "verified_exact"
                if sum(len(matches) for matches in all_matches.values()) > 1:
                    item["status"] = "ambiguous_match"
                    item["findings"].append(self._finding(
                        "ambiguous_match", "review_flag", "The quotation has multiple possible source occurrences; claimed-source existence is verified, unique location is not."
                    ))
                context_findings, suggestions = self._context_findings(claimed, quote)
                item["findings"].extend(context_findings)
                item["suggested_blocks"] = suggestions
            selected = claimed if claimed else [match for matches in all_matches.values() for match in matches]
            if not claimed:
                item["suggested_blocks"] = [
                    {"source": match["source"], **_block_description(block, include_text=True)}
                    for match in selected for block in match["_containing"]
                ]
            item["matches"] = [{key: value for key, value in match.items() if key != "_containing"} for match in selected]
        for item in items:
            item["requires_review"] = bool(item["findings"])
            item["quarantine_recommended"] = not item["provenance_verified"] or item["requires_review"]
            item["accepted"] = not item["quarantine_recommended"]
        statuses = Counter(item["status"] for item in items)
        classifications = Counter(finding["classification"] for item in items for finding in item["findings"])
        return {
            "schema_version": 1, "semantic_correctness_assessed": False,
            "items": items,
            "summary": {"evidence_items": len(items), "statuses": dict(sorted(statuses.items())),
                        "provenance_verified_items": sum(item["provenance_verified"] for item in items),
                        "confirmed_provenance_failures": classifications["confirmed_provenance_failure"],
                        "review_flags": classifications["review_flag"], "schema_errors": classifications["schema_error"],
                        "quarantine_items": sum(item["quarantine_recommended"] for item in items)},
            "accepted": all(item["accepted"] for item in items),
            "requires_review": any(item["requires_review"] for item in items),
            "quarantine_recommended": any(item["quarantine_recommended"] for item in items),
            "projection_diagnostics": self.projection_diagnostics,
            "limitations": _LIMITATION,
        }


def validate_evidence(evidence: object, corpus: dict[str, ParsedDocument]) -> dict:
    return EvidenceProvenanceValidator(corpus).validate_evidence(evidence)


def load_tenant_corpus(tenant_dir: Path | str) -> dict[str, ParsedDocument]:
    """Use the same eligibility, exact relative IDs and containment as generation/RAG."""
    return load_documents(Path(tenant_dir), include_reference=False)


def audit_evidence_csv(csv_path: Path | str, data_root: Path | str, *, tenants: set[str] | None = None,
                       include_verified: bool = False) -> dict:
    """Read an existing training/development CSV. Never alters a dataset or benchmark."""
    csv_path, data_root = Path(csv_path), Path(data_root)
    if csv_path.suffix.lower() != ".csv":
        raise ValueError("Audit requires an existing training/development CSV, not a benchmark JSON")
    original_bytes = csv_path.read_bytes()
    validators, corpus_manifest, results = {}, {}, []
    totals, status_counts, findings = Counter(), Counter(), Counter()
    tenant_counts = Counter()
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"ticket_id", "business", "evidence_json"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("CSV must contain ticket_id, business, and evidence_json columns")
        for row_number, row in enumerate(reader, 2):
            tenant = row.get("business") or ""
            if tenants is not None and tenant not in tenants:
                continue
            if not tenant or Path(tenant).name != tenant or tenant in {".", ".."}:
                raise ValueError(f"Invalid tenant directory name at CSV row {row_number}")
            if tenant not in validators:
                if not (data_root / tenant).resolve().is_relative_to(data_root.resolve()):
                    raise ValueError("Tenant directory symlink escapes data-root")
                corpus = load_tenant_corpus(data_root / tenant)
                validators[tenant] = EvidenceProvenanceValidator(corpus)
                corpus_manifest[tenant] = {source: {"sha256": doc.sha256, "blocks": len(doc.blocks)}
                                           for source, doc in corpus.items()}
            try:
                evidence = json.loads(row["evidence_json"], object_pairs_hook=_unique_object)
            except (ValueError, TypeError):
                evidence = None
            report = validators[tenant].validate_evidence(evidence)
            totals["rows"] += 1
            tenant_counts[tenant] += 1
            totals["rows_flagged"] += report["requires_review"]
            totals["rows_quarantine_recommended"] += report["quarantine_recommended"]
            totals["rows_with_confirmed_provenance_failure"] += report["summary"]["confirmed_provenance_failures"] > 0
            for key in ("evidence_items", "provenance_verified_items", "confirmed_provenance_failures", "review_flags", "schema_errors"):
                totals[key] += report["summary"][key]
            status_counts.update(report["summary"]["statuses"])
            findings.update(finding["code"] for item in report["items"] for finding in item["findings"])
            if include_verified or report["requires_review"]:
                results.append({"csv_row": row_number, "ticket_id": row["ticket_id"], "tenant": tenant, **report})
    if csv_path.read_bytes() != original_bytes:
        raise ValueError("Input CSV changed during read-only audit; no report can certify a stable input")
    return {
        "schema_version": 1, "audit": "source_aware_evidence_provenance_only",
        "input_csv": str(csv_path.resolve()), "input_sha256": hashlib.sha256(original_bytes).hexdigest(),
        "input_unchanged": True, "network_calls": 0, "dataset_writes": 0,
        "semantic_correctness_assessed": False, "limitations": _LIMITATION,
        "summary": {**dict(totals), "tenant_rows": dict(sorted(tenant_counts.items())),
                    "statuses": dict(sorted(status_counts.items())), "findings": dict(sorted(findings.items()))},
        "corpus": corpus_manifest, "included_verified_rows": include_verified,
        "rows": results,
    }
