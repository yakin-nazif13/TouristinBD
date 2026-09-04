"""Phase 12 — tests for the deployment configuration.

Deployment breaks in ways that are invisible locally: a dependency the venv
happens to have but the host does not, a data file that is gitignored and so
never reaches the build, a start command binding to loopback inside a
container. These tests check those specific failure modes without needing
Docker or a host account.

Run:
    .venv/bin/python scripts/test_phase12_deployment.py
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402

client = TestClient(app)

PASSED: list[str] = []
FAILED: list[str] = []

# Import name -> distribution that provides it, for the requirements check.
THIRD_PARTY = {
    "fastapi": "fastapi",
    "starlette": "fastapi",
    "pydantic": "fastapi",
    "uvicorn": "uvicorn",
    "pandas": "pandas",
    "httpx": "httpx",
    "numpy": "pandas",
}
# Imported only by the research pipeline (Phases 3-7), which the deployment
# never runs — they must stay out of the slim requirements file.
PIPELINE_ONLY = {"torch", "bertopic", "sentence_transformers", "sklearn", "matplotlib", "scipy", "hdbscan", "umap", "openai", "dotenv", "langdetect"}


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(f"{name}: {detail}")
        print(f"  FAIL  {name} — {detail}")


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_files_present() -> None:
    print("\ndeployment — required files")
    for path in (
        "Dockerfile",
        ".dockerignore",
        "render.yaml",
        "requirements-api.txt",
        "docs/DEPLOYMENT.md",
        ".github/workflows/ci.yml",
    ):
        check(f"{path} exists", (REPO_ROOT / path).exists(), "missing")


def test_requirements_cover_runtime() -> None:
    print("\ndeployment — the slim requirements really cover the service")
    listed = {
        line.split("[")[0].split("==")[0].split(">=")[0].strip().lower()
        for line in read("requirements-api.txt").splitlines()
        if line.strip() and not line.startswith("#")
    }
    check("requirements-api.txt lists packages", listed, "empty")

    runtime_files = sorted((REPO_ROOT / "backend").rglob("*.py"))
    runtime_files.append(REPO_ROOT / "scripts" / "build_phase8_database.py")
    imported: set[str] = set()
    for path in runtime_files:
        imported |= top_level_imports(path)

    stdlib = set(sys.stdlib_module_names)
    external = {n for n in imported if n not in stdlib and n != "backend"}
    unmapped = sorted(n for n in external if n not in THIRD_PARTY)
    check("every runtime import is a known distribution", not unmapped, str(unmapped))
    missing = sorted({THIRD_PARTY[n] for n in external if n in THIRD_PARTY} - listed)
    check("requirements-api.txt covers every runtime import", not missing, str(missing))

    heavy = sorted(listed & PIPELINE_ONLY)
    check(
        "pipeline-only packages stay out of the deployment requirements",
        not heavy,
        f"{heavy} would blow up a free-tier build",
    )
    check(
        "the service itself imports no pipeline-only package",
        not (external & PIPELINE_ONLY),
        str(sorted(external & PIPELINE_ONLY)),
    )
    full = read("requirements.txt")
    check(
        "the research requirements file still exists for the pipeline",
        "bertopic" in full and "torch" in full,
        "requirements.txt lost its pipeline deps",
    )


def test_container_config() -> None:
    print("\ndeployment — Dockerfile")
    dockerfile = read("Dockerfile")
    check("installs the slim requirements", "requirements-api.txt" in dockerfile, "not referenced")
    check(
        "builds the database during the image build",
        "scripts/build_phase8_database.py" in dockerfile,
        "database would be missing at runtime",
    )
    check(
        "runs the test suites so a broken image fails the build",
        "scripts/test_phase8_api.py" in dockerfile and "scripts/test_phase10_itinerary.py" in dockerfile,
        "no verification step",
    )
    check("binds 0.0.0.0 for the container", "HOST=0.0.0.0" in dockerfile, "would bind loopback only")
    check("declares a healthcheck", "HEALTHCHECK" in dockerfile, "missing")
    check(
        "copies everything the service reads",
        all(f"COPY {d}/" in dockerfile for d in ("backend", "frontend", "scripts", "data")),
        "a needed directory is not copied",
    )
    version = next((ln for ln in dockerfile.splitlines() if ln.startswith("FROM python:")), "")
    minor = int(version.split("python:")[1].split("-")[0].split(".")[1]) if version else 0
    check(
        "uses Python 3.10+ (the type syntax the models rely on)",
        minor >= 10,
        version or "no FROM line",
    )

    ignored = read(".dockerignore")
    check(
        "the built database is not copied into the image",
        "data/touristinbd.db" in ignored,
        "a stale local DB could be baked in",
    )
    check(
        "the model directory and charts stay out of the image",
        "bertopic_model_dir/" in ignored and "*.png" in ignored,
        "image would carry research-only files",
    )
    check("secrets stay out of the image", ".env" in ignored, ".env not ignored")


def test_host_config() -> None:
    print("\ndeployment — managed host blueprint")
    render = read("render.yaml")
    check("declares a web service", "type: web" in render, "no web service")
    check(
        "builds the database in the build step",
        "build_phase8_database.py" in render,
        "the service would start with no database",
    )
    check("starts the app module", "python -m backend.main" in render, "no start command")
    check("uses /health as the health check", "healthCheckPath: /health" in render, "missing")
    check("binds 0.0.0.0", "0.0.0.0" in render, "would bind loopback only")
    check(
        "installs only the slim requirements",
        "requirements-api.txt" in render and "-r requirements.txt" not in render,
        "would install the pipeline stack",
    )

    ci = read(".github/workflows/ci.yml")
    for script in (
        "test_phase2_preprocessing.py",
        "test_phase8_api.py",
        "test_phase8_rebuild.py",
        "test_phase9_chat.py",
        "test_phase10_itinerary.py",
        "test_phase11_frontend.py",
        "test_phase12_deployment.py",
    ):
        check(f"CI runs {script}", script in ci, "not in the workflow")
    referenced = {
        line.split("python ")[1].strip()
        for line in ci.splitlines()
        if "run: python scripts/" in line
    }
    missing = sorted(s for s in referenced if not (REPO_ROOT / s).exists())
    check("every script CI references exists", not missing, str(missing))


def test_env_binding() -> None:
    print("\ndeployment — HOST/PORT come from the environment")
    import backend.main as main

    captured: dict = {}
    stub = types.SimpleNamespace(run=lambda target, **kw: captured.update(kw, target=target))
    saved = sys.modules.get("uvicorn")
    sys.modules["uvicorn"] = stub
    previous = {k: os.environ.get(k) for k in ("HOST", "PORT")}
    os.environ["HOST"] = "0.0.0.0"
    os.environ["PORT"] = "10000"
    try:
        main.run()
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if saved is None:
            sys.modules.pop("uvicorn", None)
        else:
            sys.modules["uvicorn"] = saved

    check("host comes from $HOST", captured.get("host") == "0.0.0.0", str(captured.get("host")))
    check("port comes from $PORT", captured.get("port") == 10000, str(captured.get("port")))
    check("auto-reload is off in production", captured.get("reload") is False, str(captured.get("reload")))

    sys.modules["uvicorn"] = stub
    try:
        main.run()
    finally:
        if saved is None:
            sys.modules.pop("uvicorn", None)
        else:
            sys.modules["uvicorn"] = saved
    check(
        "defaults stay loopback:8000 without the env vars",
        captured.get("host") == "127.0.0.1" and captured.get("port") == 8000,
        f"{captured.get('host')}:{captured.get('port')}",
    )


def test_data_ships() -> None:
    print("\ndeployment — the data the build needs is committed")
    try:
        tracked = set(
            subprocess.run(
                ["git", "ls-files", "data"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.split()
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        check("git is available to list tracked files", False, str(exc))
        return

    required = [
        "data/processed_reviews.csv",
        "data/reviews_with_topics.csv",
        "data/topics_summary.csv",
        "data/preference_classification.csv",
        "data/topic_preference_mapping.csv",
        "data/place_geography.csv",
    ]
    for path in required:
        check(f"{path} is committed", path in tracked, "gitignored or untracked — deploy would degrade")

    ignored = read(".gitignore")
    check("the built database stays out of git", "data/touristinbd.db" in ignored, "db is tracked")
    check("the .env file stays out of git", ".env" in ignored, ".env not ignored")
    check(
        "no API key was committed",
        "GEMINI_API_KEY=your-gemini-key-here" in read(".env.example")
        and not any(
            token in read(".env.example") for token in ("AIza", "sk-proj-", "sk-ant-")
        ),
        ".env.example carries a real-looking key",
    )


def test_service_contract() -> None:
    print("\ndeployment — the running service behaves as a host expects")
    r = client.get("/health")
    check("/health answers 200", r.status_code == 200, str(r.status_code))
    body = r.json()
    check("/health reports the database state", body.get("database") == "ready", str(body))
    check(
        "/health carries the build stamp a deploy can be verified against",
        body.get("schema_version") is not None and body.get("built_at_utc"),
        str(body),
    )
    check(
        "the API version was bumped for the release",
        client.get("/openapi.json").json()["info"]["version"] == "1.0.0",
        client.get("/openapi.json").json()["info"]["version"],
    )
    meta = client.get("/api/meta").json()
    check(
        "meta documents every phase, including the new ones",
        {"phase9", "phase10", "phase11", "phase12"} <= set(meta["pipeline_phases"]),
        str(sorted(meta["pipeline_phases"])),
    )
    r = client.options(
        "/api/chat",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    check(
        "CORS allows a browser on another origin to POST",
        r.status_code in (200, 204)
        and "POST" in r.headers.get("access-control-allow-methods", ""),
        f"{r.status_code} {r.headers.get('access-control-allow-methods')}",
    )
    check(
        "the interface is served by the same origin as the API",
        client.get("/app/").status_code == 200,
        "frontend not mounted",
    )


def main() -> None:
    print("Phase 12 — deployment configuration tests")
    test_files_present()
    test_requirements_cover_runtime()
    test_container_config()
    test_host_config()
    test_env_binding()
    test_data_ships()
    test_service_contract()

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    print("All Phase 12 deployment tests passed.")


if __name__ == "__main__":
    main()
