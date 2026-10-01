"""domain 계층이 외부 라이브러리와 다른 계층에 의존하지 않는지 검사한다 (project.md 4절)."""

import ast
from pathlib import Path

import quant_lab

DOMAIN_DIR = Path(quant_lab.__file__).parent / "domain"
FORBIDDEN = (
    "fastapi",
    "starlette",
    "httpx",
    "sqlalchemy",
    "psycopg",
    "alembic",
    "pydantic_settings",
    "quant_lab.adapters",
    "quant_lab.application",
    "quant_lab.api",
    "quant_lab.persistence",
    "quant_lab.worker",
    "quant_lab.config",
)


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_domain_has_no_forbidden_imports() -> None:
    violations = [
        f"{path.relative_to(DOMAIN_DIR)}: {name}"
        for path in DOMAIN_DIR.rglob("*.py")
        for name in imported_modules(path)
        if any(name == f or name.startswith(f + ".") for f in FORBIDDEN)
    ]
    assert violations == []
