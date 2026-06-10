from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
STORAGE_DIR = ROOT_DIR / "storage" / "projects"
EXPORTS_DIR = ROOT_DIR / "exports"
BUILDS_DIR = EXPORTS_DIR / "builds"


def ensure_runtime_dirs() -> None:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    BUILDS_DIR.mkdir(parents=True, exist_ok=True)

