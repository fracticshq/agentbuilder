#!/usr/bin/env python3
"""Generate the Postman collection from the committed OpenAPI contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
HTTP_METHODS = ("get", "post", "put", "patch", "delete", "options", "head")


def _resolve(schema: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    reference = schema.get("$ref") if isinstance(schema, dict) else None
    if not isinstance(reference, str) or not reference.startswith("#/components/schemas/"):
        return schema if isinstance(schema, dict) else {}
    return document.get("components", {}).get("schemas", {}).get(reference.rsplit("/", 1)[-1], {})


def _example(schema: dict[str, Any], document: dict[str, Any], *, depth: int = 0) -> Any:
    if depth > 4:
        return "value"
    schema = _resolve(schema, document)
    if "example" in schema:
        return schema["example"]
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return enum[0]
    if "default" in schema:
        return schema["default"]
    schema_type = schema.get("type")
    if schema_type == "object" or "properties" in schema:
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        return {name: _example(value, document, depth=depth + 1) for name, value in properties.items()}
    if schema_type == "array":
        return [_example(schema.get("items", {}), document, depth=depth + 1)]
    if schema_type == "integer":
        return 0
    if schema_type == "number":
        return 0
    if schema_type == "boolean":
        return False
    return "value"


def _request_body(operation: dict[str, Any], document: dict[str, Any]) -> dict[str, Any] | None:
    body = operation.get("requestBody") if isinstance(operation.get("requestBody"), dict) else None
    if not body:
        return None
    content = body.get("content") if isinstance(body.get("content"), dict) else {}
    if "application/json" in content:
        schema = content["application/json"].get("schema", {})
        return {"mode": "raw", "raw": json.dumps(_example(schema, document), indent=2), "options": {"raw": {"language": "json"}}}
    multipart = content.get("multipart/form-data")
    if isinstance(multipart, dict):
        schema = _resolve(multipart.get("schema", {}), document)
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        formdata = []
        for name, field in properties.items():
            field = _resolve(field, document)
            is_file = field.get("format") == "binary"
            formdata.append({"key": name, "type": "file" if is_file else "text", "src": "" if is_file else None, "value": "" if is_file else str(_example(field, document))})
        return {"mode": "formdata", "formdata": formdata}
    return None


def _auth(operation: dict[str, Any]) -> dict[str, Any] | None:
    """Map FastAPI's HTTP bearer OpenAPI security marker to Postman auth."""
    if not operation.get("security"):
        return None
    return {
        "type": "bearer",
        "bearer": [{"key": "token", "value": "{{accessToken}}", "type": "string"}],
    }


def generate(document: dict[str, Any]) -> dict[str, Any]:
    info = document.get("info", {})
    raw_openapi = json.dumps(document, sort_keys=True, separators=(",", ":"))
    folders: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path, path_item in sorted(document.get("paths", {}).items()):
        if not isinstance(path_item, dict):
            continue
        for method in HTTP_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            headers = [{"key": "Accept", "value": "application/json"}]
            if _request_body(operation, document) and _request_body(operation, document).get("mode") == "raw":
                headers.append({"key": "Content-Type", "value": "application/json"})
            request: dict[str, Any] = {
                "method": method.upper(),
                "header": headers,
                "url": "{{baseUrl}}" + re.sub(r"\{([^}]+)\}", r":\1", path),
                "description": operation.get("description") or operation.get("summary") or "",
            }
            body = _request_body(operation, document)
            if body:
                request["body"] = body
            auth = _auth(operation)
            if auth:
                request["auth"] = auth
            folders[(operation.get("tags") or ["Other"])[0]].append({
                "name": operation.get("operationId") or f"{method.upper()} {path}",
                "request": request,
                "response": [],
            })

    return {
        "info": {
            "_postman_id": str(uuid.UUID(bytes=hashlib.sha256(raw_openapi.encode("utf-8")).digest()[:16])),
            "name": f"{info.get('title', 'Agent Builder API')} (generated)",
            "description": "Generated from docs/api/openapi.json. Do not edit manually.",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "variable": [
            {"key": "baseUrl", "value": "http://localhost:8000"},
            {"key": "accessToken", "value": ""},
            {"key": "widgetSession", "value": ""},
        ],
        "item": [{"name": tag, "item": items} for tag, items in sorted(folders.items())],
    }


def encoded(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--openapi", type=Path, default=ROOT / "docs/api/openapi.json")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/api/Agent_Builder_Platform.postman_collection.json")
    parser.add_argument("--check", action="store_true", help="fail if the committed collection is stale")
    args = parser.parse_args()
    root = args.root.resolve()
    openapi_path = args.openapi if args.openapi.is_absolute() else root / args.openapi
    output = args.output if args.output.is_absolute() else root / args.output
    content = encoded(generate(json.loads(openapi_path.read_text(encoding="utf-8"))))

    if args.check:
        actual = output.read_text(encoding="utf-8") if output.is_file() else ""
        if actual != content:
            raise SystemExit("Postman collection is stale: regenerate from docs/api/openapi.json")
        print(f"Generated Postman collection is current: {output}")
        return 0

    output.write_text(content, encoding="utf-8")
    print(f"Generated Postman collection: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
