"""domain 계층이 외부 라이브러리와 다른 계층에 의존하지 않는지 검사한다 (project.md 4절)."""

import ast
from pathlib import Path

import trading_lab

DOMAIN_DIR = Path(trading_lab.__file__).parent / "domain"
FORBIDDEN = (
    "fastapi",
    "starlette",
    "httpx",
    "sqlalchemy",
    "psycopg",
    "alembic",
    "pydantic_settings",
    "trading_lab.adapters",
    "trading_lab.application",
    "trading_lab.api",
    "trading_lab.persistence",
    "trading_lab.worker",
    "trading_lab.config",
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


# 증권사(토스)·AI 공급자(Claude)를 직접 아는 곳은 어댑터와 조립 지점(Worker 진입점·CLI)뿐이다
# (domain/broker.py·domain/advisor.py 규약).
BROKER_ASSEMBLY = {"cli.py", "worker/__main__.py"}
PROVIDERS = ("toss", "claude", "anthropic")


def test_only_assembly_points_know_the_broker() -> None:
    root = DOMAIN_DIR.parent
    violations = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if "adapters" not in path.relative_to(root).parts
        and path.relative_to(root).as_posix() not in BROKER_ASSEMBLY
        and any(
            n.startswith(("trading_lab.adapters.toss", "trading_lab.adapters.claude"))
            for n in imported_modules(path)
        )
    ]
    assert violations == []


def test_engine_code_does_not_name_the_broker() -> None:
    """엔진·저장소·API의 이름과 값에 증권사·AI 공급자 이름이 없다 (project.md 4절·14절).

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
            if any(p in s.lower() for p in PROVIDERS):
                violations.append(f"{rel.as_posix()}:{getattr(node, 'lineno', '?')} {s[:40]}")
    assert violations == []


# 계층의 방향: domain ← persistence·adapters ← application ← api·worker.
# 어긋나게 import하면 안 되는 쪽만 적는다 (api가 어댑터를 직접 아는 곳은 따로 정리한다).
FORBIDDEN_UP = {
    "persistence": ("application", "adapters", "api", "worker"),
    "adapters": ("application", "persistence", "api", "worker"),
    "application": ("adapters", "api", "worker"),
}


def test_layers_only_depend_downward() -> None:
    root = DOMAIN_DIR.parent
    violations = [
        f"{path.relative_to(root).as_posix()}: {name}"
        for layer, upper in FORBIDDEN_UP.items()
        for path in (root / layer).rglob("*.py")
        for name in imported_modules(path)
        if any(name == f"trading_lab.{u}" or name.startswith(f"trading_lab.{u}.") for u in upper)
    ]
    assert violations == []


def test_queries_are_built_only_in_persistence() -> None:
    """application·api·worker는 sqlalchemy 본체(select·func 등)를 쓰지 않는다.

    Session(`sqlalchemy.orm`)과 오류(`sqlalchemy.exc`)는 쓸 수 있다. 조회·집계는 이름을 붙인
    persistence 함수로 두어, 쿼리가 계층마다 흩어지지 않게 한다.
    """
    root = DOMAIN_DIR.parent
    violations = [
        path.relative_to(root).as_posix()
        for layer in ("application", "api", "worker")
        for path in (root / layer).rglob("*.py")
        if "sqlalchemy" in imported_modules(path)
    ]
    assert violations == []
