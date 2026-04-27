from __future__ import annotations

import asyncio
import argparse
import json

from app.bootstrap.atlas_admin import AtlasAdminClient, has_atlas_admin_credentials
from app.bootstrap.atlas_vector import check_atlas_vector_index
from app.bootstrap.database import bootstrap_database, brand_database_names
from app.bootstrap.qdrant import ensure_qdrant_collections
from app.config import Settings
from app.connections import connection_manager


def _symbol(status: str) -> str:
    return {"ok": "✓", "manual": "!", "error": "✗", "skipped": "-"}.get(status, "-")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap NOVA MongoDB and vector-search resources.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create or update managed vector-search resources when credentials are configured.",
    )
    return parser.parse_args()


async def run(*, apply: bool | None = None) -> int:
    settings = Settings()
    apply_changes = settings.ATLAS_AUTO_CREATE_VECTOR_INDEXES if apply is None else apply
    print("NOVA Database Bootstrap")
    print(f"Vector backend: {settings.VECTOR_BACKEND}")
    print(f"Apply managed changes: {'yes' if apply_changes else 'no'}")

    checks = await bootstrap_database(settings)
    db_names: list[str] = []
    if connection_manager.mongodb_client is not None and connection_manager.system_db is not None:
        db_names = await brand_database_names(settings)

    if settings.VECTOR_BACKEND == "atlas" and connection_manager.mongodb_client is not None:
        if has_atlas_admin_credentials(settings) or apply_changes:
            async with AtlasAdminClient(settings) as atlas_admin:
                for db_name in db_names:
                    checks.append(await atlas_admin.ensure_vector_index(db_name, apply=apply_changes))
        else:
            for db_name in db_names:
                checks.append(await check_atlas_vector_index(connection_manager.mongodb_client[db_name], settings))
    elif settings.VECTOR_BACKEND == "qdrant":
        checks.extend(await ensure_qdrant_collections(settings, db_names))
    else:
        checks.append({
            "name": "vector_backend",
            "status": "error",
            "detail": f"Unsupported VECTOR_BACKEND={settings.VECTOR_BACKEND}. Use atlas or qdrant.",
        })

    has_error = False
    needs_manual = False
    for check in checks:
        if isinstance(check, dict):
            name = check["name"]
            status = check["status"]
            detail = check.get("detail", "")
            metadata = check.get("metadata", {})
        else:
            name = check.name
            status = check.status
            detail = check.detail
            metadata = check.metadata
        has_error = has_error or status == "error"
        needs_manual = needs_manual or status == "manual"
        print(f"{_symbol(status)} {name}: {status} {('- ' + detail) if detail else ''}")
        if metadata.get("definition"):
            print(json.dumps(metadata["definition"], indent=2))

    await connection_manager.close_all()
    if has_error:
        return 1
    return 2 if needs_manual else 0


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(asyncio.run(run(apply=args.apply or None)))
