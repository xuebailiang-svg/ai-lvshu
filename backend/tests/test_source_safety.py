import ast
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_backend_has_no_duplicate_top_level_definitions():
    duplicates = []
    for path in (PROJECT_ROOT / "backend").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        duplicates.extend(
            f"{path.relative_to(PROJECT_ROOT)}:{name}"
            for name, count in Counter(names).items()
            if count > 1
        )
    assert duplicates == []


def test_known_insecure_defaults_are_not_present():
    checked_files = [
        PROJECT_ROOT / "install.sh",
        PROJECT_ROOT / "backend/app/core/config.py",
        PROJECT_ROOT / "backend/app/db/init_db.py",
        PROJECT_ROOT / "frontend/src/views/LoginView.vue",
    ]
    contents = "\n".join(path.read_text(encoding="utf-8") for path in checked_files)
    assert "CHANGE_ME_TO_A_RANDOM_SECRET_KEY_AT_LEAST_32_CHARS" not in contents
    assert "admin / admin123" not in contents
    assert 'BACKEND_CORS_ORIGINS: List[str] = ["*"]' not in contents


def test_core_database_initialization_is_not_silently_swallowed():
    tree = ast.parse((PROJECT_ROOT / "backend/main.py").read_text(encoding="utf-8"))
    lifespan = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan"
    )
    assert not any(isinstance(node, ast.ExceptHandler) for node in ast.walk(lifespan))
