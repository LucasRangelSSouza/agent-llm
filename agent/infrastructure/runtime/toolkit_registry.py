import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


REGISTRY_PATH = Path(__file__).resolve().parents[2] / "tools" / "toolkits.registry.json"


@dataclass(frozen=True)
class ToolkitFunctionSpec:
    toolkit_name: str
    function_name: str
    method_name: str
    description: str

    @property
    def tool_name(self) -> str:
        return f"{self.toolkit_name}.{self.function_name}"


def load_toolkit_registry() -> Dict[str, Any]:
    if not REGISTRY_PATH.exists():
        return {"version": 1, "toolkits": [], "aliases": {}}
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def get_toolkit_aliases() -> Dict[str, str]:
    registry = load_toolkit_registry()
    aliases = registry.get("aliases") or {}
    return {str(key): str(value) for key, value in aliases.items()}


def normalize_tool_name(tool_name: str) -> str:
    clean_name = (tool_name or "").strip()
    return get_toolkit_aliases().get(clean_name, clean_name)


def iter_enabled_toolkits() -> Iterable[Dict[str, Any]]:
    registry = load_toolkit_registry()
    for toolkit in registry.get("toolkits") or []:
        if toolkit.get("enabled", True):
            yield toolkit


def get_function_spec(tool_name: str) -> Optional[ToolkitFunctionSpec]:
    normalized = normalize_tool_name(tool_name)
    if "." not in normalized:
        return None
    toolkit_name, function_name = normalized.split(".", 1)
    for toolkit in iter_enabled_toolkits():
        if toolkit.get("name") != toolkit_name:
            continue
        for function in toolkit.get("functions") or []:
            if function.get("name") == function_name:
                return ToolkitFunctionSpec(
                    toolkit_name=toolkit_name,
                    function_name=function_name,
                    method_name=function.get("method") or function_name,
                    description=function.get("description") or toolkit.get("description") or "",
                )
    return None


def load_toolkit_class(toolkit_name: str):
    for toolkit in iter_enabled_toolkits():
        if toolkit.get("name") != toolkit_name:
            continue
        module = importlib.import_module(toolkit["module"])
        return getattr(module, toolkit["class"])
    raise KeyError(f"Toolkit '{toolkit_name}' nao encontrado no registry.")
