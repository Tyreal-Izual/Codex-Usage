"""Load repository-owned assets without a build step or public file server."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def asset_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def load_page(name: str) -> str:
    return (asset_text(f"templates/{name}.html")
            .replace("__CSS__", asset_text(f"static/{name}.css"))
            .replace("__JS__", asset_text(f"static/{name}.js")))
