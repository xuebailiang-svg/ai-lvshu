"""Reset deploy-time business data while preserving sensitive configuration.

Default behavior preserves:
- system_configs: API keys and system settings.
- users, tenants: internal user accounts for customer-side multi-user testing.

Use --clear-accounts only when you intentionally want to rebuild accounts too.
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


BASE_PRESERVED_TABLES = {"system_configs"}
ACCOUNT_TABLES = ["users", "tenants"]

RESET_TABLES = [
    "document_insights",
    "knowledge_documents",
    "hardware_configs",
    "member_profiles",
    "revenue_records",
    "upload_records",
    "competitor_observations",
    "competitor_profiles",
    "stores",
    "evaluation_feedback",
    "data_quality_issues",
    "excluded_knowledge_sources",
    "evaluation_records",
    "analysis_insights",
    "scoring_model_versions",
    "scoring_rules",
    "knowledge_vectors",
    "chat_messages",
    "chat_sessions",
    "episodic_memories",
    "semantic_memories",
    "procedural_memories",
]


def preserved_tables(clear_accounts: bool = False) -> set[str]:
    if clear_accounts:
        return set(BASE_PRESERVED_TABLES)
    return set(BASE_PRESERVED_TABLES).union(ACCOUNT_TABLES)


def _existing_tables(db: Session, table_names: list[str], preserved: set[str]) -> list[str]:
    rows = db.execute(
        text("""
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
              AND tablename = ANY(:table_names)
        """),
        {"table_names": table_names},
    ).fetchall()
    existing = {row[0] for row in rows}
    return [name for name in table_names if name in existing and name not in preserved]


def reset_deploy_data(db: Session, clear_accounts: bool = False) -> list[str]:
    """Clear redeploy-reset data; preserve users/tenants unless explicitly requested."""
    tables_to_check = list(RESET_TABLES)
    if clear_accounts:
        tables_to_check.extend(ACCOUNT_TABLES)
    tables = _existing_tables(db, tables_to_check, preserved_tables(clear_accounts))
    if not tables:
        logger.info("[deploy-reset] No reset tables exist yet; skipped data cleanup.")
        return []

    quoted = ", ".join(f'"{name}"' for name in tables)
    db.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))
    db.commit()
    logger.info("[deploy-reset] Cleared tables: %s", ", ".join(tables))
    return tables


def _is_safe_upload_path(resolved: Path, deploy_root: Path) -> bool:
    if resolved == Path("/") or len(resolved.parts) < 3:
        return False
    if resolved == deploy_root or deploy_root in resolved.parents:
        return True
    return "uploads" in {part.lower() for part in resolved.parts}


def _safe_clear_directory(path: Path, deploy_root: Path) -> bool:
    resolved = path.expanduser().resolve()
    deploy_root = deploy_root.expanduser().resolve()
    if not resolved.exists():
        return False
    if not _is_safe_upload_path(resolved, deploy_root):
        raise RuntimeError(f"Refusing to clear unsafe upload path: {resolved}")
    for child in resolved.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    logger.info("[deploy-reset] Cleared upload files under: %s", resolved)
    return True


def clear_upload_files() -> list[str]:
    backend_dir = Path(__file__).resolve().parents[2]
    deploy_root = backend_dir.parent
    candidates = {
        Path(os.environ.get("UPLOAD_ROOT", "")) if os.environ.get("UPLOAD_ROOT") else None,
        deploy_root / "data" / "uploads",
        backend_dir / "data" / "uploads",
    }
    cleared = []
    for candidate in candidates:
        if candidate is None:
            continue
        if _safe_clear_directory(candidate, deploy_root):
            cleared.append(str(candidate))
    return cleared


def main() -> None:
    parser = argparse.ArgumentParser(description="Clear deploy-time business data while preserving API keys.")
    parser.add_argument("--yes", action="store_true", help="Required confirmation flag.")
    parser.add_argument("--clear-files", action="store_true", help="Also clear uploaded source files under the deploy root.")
    parser.add_argument("--clear-accounts", action="store_true", help="Also clear users and tenants. Use with care.")
    args = parser.parse_args()
    if not args.yes:
        raise SystemExit("Refusing to reset data without --yes")

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    db = SessionLocal()
    try:
        cleared_tables = reset_deploy_data(db, clear_accounts=args.clear_accounts)
        cleared_dirs = clear_upload_files() if args.clear_files else []
        print(f"[deploy-reset] preserved tables: {', '.join(sorted(preserved_tables(args.clear_accounts)))}")
        print(f"[deploy-reset] cleared tables: {', '.join(cleared_tables) if cleared_tables else 'none'}")
        print(f"[deploy-reset] cleared upload dirs: {', '.join(cleared_dirs) if cleared_dirs else 'none'}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
