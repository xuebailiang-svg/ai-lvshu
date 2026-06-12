"""Reset deploy-time business data while preserving system API keys.

This module is intentionally conservative about what it preserves:
- Preserve `system_configs`, because it stores AMap/LLM/embedding/reranker keys.
- Clear uploaded historical data, evaluation history, RAG/memory/chat data,
  feedback, quality issues, generated model versions, users, tenants, and
  scoring rules. `init_db` should be run after this reset to recreate the
  default tenant, admin user, and default scoring rules.
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


PRESERVED_TABLES = {"system_configs"}

RESET_TABLES = [
    # Uploads, historical operation data, and manually collected business data.
    "document_insights",
    "knowledge_documents",
    "hardware_configs",
    "member_profiles",
    "revenue_records",
    "upload_records",
    "competitor_observations",
    "competitor_profiles",
    "stores",
    # Analysis/model/evaluation loop data.
    "evaluation_feedback",
    "data_quality_issues",
    "excluded_knowledge_sources",
    "evaluation_records",
    "analysis_insights",
    "scoring_model_versions",
    "scoring_rules",
    # RAG, memory, and chat tables created outside ORM metadata.
    "knowledge_vectors",
    "chat_messages",
    "chat_sessions",
    "episodic_memories",
    "semantic_memories",
    "procedural_memories",
    # User/tenant records are recreated by init_db after deploy reset.
    "users",
    "tenants",
]


def _existing_tables(db: Session, table_names: list[str]) -> list[str]:
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
    return [name for name in table_names if name in existing and name not in PRESERVED_TABLES]


def reset_deploy_data(db: Session) -> list[str]:
    """Clear all redeploy-reset data and preserve system_configs."""
    tables = _existing_tables(db, RESET_TABLES)
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
    """Clear uploaded source files from known upload roots under the deploy root."""
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
    parser = argparse.ArgumentParser(description="Clear deploy-time business data while preserving system_configs.")
    parser.add_argument("--yes", action="store_true", help="Required confirmation flag.")
    parser.add_argument("--clear-files", action="store_true", help="Also clear uploaded source files under the deploy root.")
    args = parser.parse_args()
    if not args.yes:
        raise SystemExit("Refusing to reset data without --yes")

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    db = SessionLocal()
    try:
        cleared_tables = reset_deploy_data(db)
        cleared_dirs = clear_upload_files() if args.clear_files else []
        print(f"[deploy-reset] preserved tables: {', '.join(sorted(PRESERVED_TABLES))}")
        print(f"[deploy-reset] cleared tables: {', '.join(cleared_tables) if cleared_tables else 'none'}")
        print(f"[deploy-reset] cleared upload dirs: {', '.join(cleared_dirs) if cleared_dirs else 'none'}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
