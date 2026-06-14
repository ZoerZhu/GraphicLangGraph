from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
STORAGE_DIR = ROOT_DIR / "storage" / "projects"
WORKSPACE_DIR = ROOT_DIR / "storage" / "workspace"
WORKSPACE_TOOLS_FILE = WORKSPACE_DIR / "tools.json"
WORKSPACE_MCP_FILE = WORKSPACE_DIR / "mcp_servers.json"
WORKSPACE_MODELS_FILE = WORKSPACE_DIR / "models.json"
WORKSPACE_RAG_FILE = WORKSPACE_DIR / "rag_knowledge_bases.json"
EXPORTS_DIR = ROOT_DIR / "exports"
BUILDS_DIR = EXPORTS_DIR / "builds"


def ensure_runtime_dirs() -> None:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    BUILDS_DIR.mkdir(parents=True, exist_ok=True)
