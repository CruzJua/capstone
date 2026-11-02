"""Inspect GGUF metadata without loading tensor weights or importing ML runtimes."""

import struct
from pathlib import Path


def read_gguf_metadata(path: str | Path) -> dict:
    """Read the v2/v3 metadata header, retaining tokenizer arrays for inspection."""
    with Path(path).open("rb") as stream:
        def read(size):
            value = stream.read(size)
            if len(value) != size:
                raise ValueError("Truncated GGUF metadata")
            return value

        def unpack(fmt):
            return struct.unpack("<" + fmt, read(struct.calcsize("<" + fmt)))[0]

        def string():
            return read(unpack("Q")).decode("utf-8")

        scalar_types = {
            0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i",
            6: "f", 7: "?", 10: "Q", 11: "q", 12: "d",
        }

        def value(kind):
            if kind == 8:
                return string()
            if kind == 9:
                subtype, count = unpack("I"), unpack("Q")
                return [value(subtype) for _ in range(count)]
            if kind not in scalar_types:
                raise ValueError(f"Unsupported GGUF metadata type: {kind}")
            return unpack(scalar_types[kind])

        if read(4) != b"GGUF":
            raise ValueError("Not a little-endian GGUF file")
        version = unpack("I")
        if version not in (2, 3):
            raise ValueError(f"Unsupported GGUF version: {version}")
        tensor_count, field_count = unpack("Q"), unpack("Q")
        metadata = {}
        for _ in range(field_count):
            key = string()
            metadata[key] = value(unpack("I"))
        return {"version": version, "tensor_count": tensor_count, "metadata": metadata}


def summarize_gguf(path: str | Path) -> dict:
    """Keep scalar metadata, original chat template, and named control tokens."""
    result = read_gguf_metadata(path)
    metadata = result["metadata"]
    result["metadata"] = {key: val for key, val in metadata.items() if not isinstance(val, list)}
    result["control_tokens"] = {
        str(index): token for index, token in enumerate(metadata.get("tokenizer.ggml.tokens", []))
        if token.startswith("<|") and not token.startswith("<|reserved_special_token_")
    }
    result["path"] = str(Path(path).resolve())
    result["size_bytes"] = Path(path).stat().st_size
    return result
