"""Read-only Ollama provenance; discovery never loads or generates with a model."""

import hashlib
import json
from collections.abc import Mapping


def response_dict(response):
    if isinstance(response, Mapping):
        return dict(response)
    if hasattr(response, "model_dump"):
        return response.model_dump(mode="json", exclude_none=True)
    raise TypeError("Expected an Ollama response object")


def parse_model_parameters(text: str) -> dict:
    """Preserve repeated stop strings while parsing declared numeric options."""
    parameters = {}
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        name, raw = parts
        try:
            value = json.loads(raw)
        except ValueError:
            value = raw
        if name == "stop":
            parameters.setdefault(name, []).append(value)
        else:
            parameters[name] = value
    return parameters


def capture_ollama_settings(client, model: str, request_options: dict) -> dict:
    """Capture installed identity/template/options and an observed runtime window.

    Missing server defaults stay unknown. Model capacity from show is never
    substituted for the runner's context window. Errors contain types only,
    since endpoint exceptions can contain private connection information.
    """
    settings = {
        "provider": "ollama", "model_requested": model,
        "model_digest": None, "template_sha256": None,
        "request_options": dict(request_options), "model_parameters": {},
        "effective_options": dict(request_options),
        "context_length": None, "context_length_source": "unknown",
        "limitations": ["Unreported server sampling defaults are not measured; resident VRAM is not peak memory."],
        "capture_errors": {},
    }
    try:
        shown = response_dict(client.show(model))
        template = shown.get("template")
        if isinstance(template, str) and template:
            settings["template"] = template
            settings["template_sha256"] = hashlib.sha256(template.encode()).hexdigest()
        parameters = parse_model_parameters(shown.get("parameters") or "")
        settings["model_parameters"] = parameters
        settings["effective_options"] = {**parameters, **request_options}
        settings["model_details"] = shown.get("details", {})
        settings["model_capacity_context_length"] = next(
            (value for key, value in shown.get("modelinfo", {}).items() if key.endswith(".context_length")), None
        )
    except Exception as exc:
        settings["capture_errors"]["show"] = type(exc).__name__

    # Match an untagged request to Ollama's explicit :latest listing.
    names = {model, model + ":latest"} if ":" not in model.rsplit("/", 1)[-1] else {model}
    try:
        installed = response_dict(client.list()).get("models", [])
        match = next((entry for entry in installed if entry.get("model") in names), None)
        if match:
            settings["model_resolved"] = match["model"]
            settings["model_digest"] = match.get("digest")
    except Exception as exc:
        settings["capture_errors"]["list"] = type(exc).__name__

    configured_context = settings["effective_options"].get("num_ctx")
    if isinstance(configured_context, int) and not isinstance(configured_context, bool) and configured_context > 0:
        settings["context_length"] = configured_context
        settings["context_length_source"] = "configured"
    try:
        running = response_dict(client.ps()).get("models", [])
        match = next((entry for entry in running if (entry.get("model") or entry.get("name")) in names), None)
        if match:
            observed_digest = match.get("digest")
            settings["runtime_model_digest"] = observed_digest
            settings["runtime_identity_mismatch"] = bool(
                observed_digest and settings["model_digest"] and observed_digest != settings["model_digest"]
            )
            window = match.get("context_length")
            if isinstance(window, int) and not isinstance(window, bool) and window > 0:
                settings["context_length"] = window
                settings["context_length_source"] = "observed_runtime"
            settings["resident_size_vram_bytes"] = match.get("size_vram")
    except Exception as exc:
        settings["capture_errors"]["ps"] = type(exc).__name__
    settings["capture_status"] = "recorded" if all(
        settings.get(key) is not None for key in ("model_digest", "template_sha256", "context_length")
    ) and not settings["capture_errors"] else "incomplete"
    return settings
