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


# 증권사(토스)를 직접 아는 곳은 어댑터와 조립 지점(Worker 진입점·CLI)뿐이다 (domain/broker.py 규약).
BROKER_ASSEMBLY = {"cli.py", "worker/__main__.py"}


def test_only_assembly_points_know_the_broker() -> None:
    root = DOMAIN_DIR.parent
    violations = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if "adapters" not in path.relative_to(root).parts
        and path.relative_to(root).as_posix() not in BROKER_ASSEMBLY
        and any(n.startswith("quant_lab.adapters.toss") for n in imported_modules(path))
    ]
    assert violations == []


def test_engine_code_does_not_name_the_broker() -> None:
    """엔진·저장소·API의 이름과 값에 증권사 이름이 없다 (project.md 4절).

    출처 코드는 어댑터가 넘긴다.

    주석·docstring은 문서 참조(tossApi.md)라 보지 않는다.
    """
    root = DOMAIN_DIR.parent
    allowed = BROKER_ASSEMBLY | {"config.py"}
    violations = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        if "adapters" in rel.parts or rel.as_posix() in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            id(n.body[0].value)
            for n in ast.walk(tree)
            if isinstance(n, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
            and n.body
            and isinstance(n.body[0], ast.Expr)
        }
        for node in ast.walk(tree):
            match node:
                case ast.Name(id=s) | ast.Attribute(attr=s) | ast.arg(arg=s):
                    pass
                case ast.FunctionDef(name=s) | ast.ClassDef(name=s) | ast.AsyncFunctionDef(name=s):
                    pass
                case ast.Constant(value=str(s)) if id(node) not in docstrings:
                    pass
                case _:
                    continue
            if "toss" in s.lower():
                violations.append(f"{rel.as_posix()}:{getattr(node, 'lineno', '?')} {s[:40]}")
    assert violations == []
