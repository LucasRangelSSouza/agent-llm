import json
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Callable


class PythonSandboxToolkit:
    """
    Executa Python em subprocesso isolado para uso por agentes universais.

    O codigo pode definir `result = ...` ou `def main(): ...`. O retorno textual
    inclui stdout, stderr e o valor final encontrado.
    """

    def __init__(self, **kwargs):
        self.context = kwargs
        self.tenant_id = kwargs.get("tenant_id")
        self.session_id = kwargs.get("session_id")
        self.user_id = kwargs.get("user_id")
        self.module_name = kwargs.get("module_name")
        self.agent_name = kwargs.get("agent_name")

    def execute_python(self) -> Callable[..., str]:
        def _tool(
            code: str,
            timeout_seconds: int = 30,
            input_artifact_url: str | None = None,
            input_artifact_id: str | None = None,
            output_label: str = "python_output",
        ) -> str:
            repo_root = str(Path(__file__).resolve().parents[2])
            wrapper = textwrap.dedent(
                """
                import json
                import sys
                import traceback
                from pathlib import Path

                sys.path.insert(0, {repo_root_literal})

                import pandas as pd
                from agent.tools.artifact_store import (
                    load_artifact_manifest,
                    load_dataset_artifact,
                    load_document_artifact,
                    save_dataset_artifact,
                    save_document_artifact,
                )

                user_namespace = {}
                user_code = {code_literal}
                INPUT_ARTIFACT_URL = {input_artifact_url_literal}
                INPUT_ARTIFACT_ID = {input_artifact_id_literal}
                OUTPUT_LABEL = {output_label_literal}
                CONTEXT = {context_literal}
                input_artifact = None
                df = None
                records = None
                document = None
                document_text = None

                if INPUT_ARTIFACT_URL or INPUT_ARTIFACT_ID:
                    manifest = load_artifact_manifest(artifact_url=INPUT_ARTIFACT_URL, artifact_id=INPUT_ARTIFACT_ID)
                    input_artifact = manifest
                    if manifest.get("artifact_kind") == "dataset":
                        _, dataframe = load_dataset_artifact(artifact_url=INPUT_ARTIFACT_URL, artifact_id=INPUT_ARTIFACT_ID)
                        df = dataframe
                        records = dataframe.to_dict(orient="records")
                    elif manifest.get("artifact_kind") == "document":
                        _, document = load_document_artifact(artifact_url=INPUT_ARTIFACT_URL, artifact_id=INPUT_ARTIFACT_ID)
                        document_text = document.get("document_summary") or document.get("answer") or ""

                def publish_dataset(data, label=None, metadata=None):
                    if isinstance(data, pd.DataFrame):
                        dataframe = data
                    elif isinstance(data, list):
                        dataframe = pd.DataFrame(data)
                    elif isinstance(data, dict) and isinstance(data.get("rows"), list):
                        dataframe = pd.DataFrame(data.get("rows") or [])
                    else:
                        raise ValueError("publish_dataset aceita DataFrame, lista de dicts ou dict com rows.")
                    return save_dataset_artifact(
                        tenant_id=CONTEXT.get("tenant_id"),
                        user_id=CONTEXT.get("user_id"),
                        chat_id=CONTEXT.get("session_id"),
                        module_name=CONTEXT.get("module_name"),
                        agent_name=CONTEXT.get("agent_name"),
                        label=label or OUTPUT_LABEL,
                        dataframe=dataframe,
                        source_tool="python_sandbox_toolkit.execute_python",
                        source_type="python_transform",
                        metadata=metadata or {},
                    )

                def publish_document(content, label=None, metadata=None):
                    payload = content if isinstance(content, dict) else {"document_summary": str(content), "answer": str(content), "chunks": []}
                    return save_document_artifact(
                        tenant_id=CONTEXT.get("tenant_id"),
                        user_id=CONTEXT.get("user_id"),
                        chat_id=CONTEXT.get("session_id"),
                        module_name=CONTEXT.get("module_name"),
                        agent_name=CONTEXT.get("agent_name"),
                        label=label or OUTPUT_LABEL,
                        content=payload,
                        source_tool="python_sandbox_toolkit.execute_python",
                        source_type="python_transform",
                        metadata=metadata or {},
                    )

                user_namespace.update({
                    "input_artifact": input_artifact,
                    "df": df,
                    "records": records,
                    "document": document,
                    "document_text": document_text,
                    "publish_dataset": publish_dataset,
                    "publish_document": publish_document,
                    "pd": pd,
                })

                try:
                    exec(user_code, user_namespace, user_namespace)
                    result = None
                    if callable(user_namespace.get("main")):
                        result = user_namespace["main"]()
                    elif "result" in user_namespace:
                        result = user_namespace.get("result")
                    print("\\n__CODEX_RESULT__=" + json.dumps(result, ensure_ascii=False, default=str))
                except Exception:
                    print("\\n__CODEX_ERROR__=" + traceback.format_exc())
                    raise
                """
            ).replace("{code_literal}", repr(code)).replace("{repo_root_literal}", repr(repo_root)).replace(
                "{input_artifact_url_literal}", repr(input_artifact_url)
            ).replace(
                "{input_artifact_id_literal}", repr(input_artifact_id)
            ).replace(
                "{output_label_literal}", repr(output_label)
            ).replace(
                "{context_literal}",
                repr(
                    {
                        "tenant_id": self.tenant_id,
                        "session_id": self.session_id,
                        "user_id": self.user_id,
                        "module_name": self.module_name,
                        "agent_name": self.agent_name,
                    }
                ),
            )

            with tempfile.TemporaryDirectory(prefix="codex_py_sandbox_") as temp_dir:
                script_path = Path(temp_dir) / "runner.py"
                script_path.write_text(wrapper, encoding="utf-8")
                try:
                    completed = subprocess.run(
                        [sys.executable, "-I", str(script_path)],
                        capture_output=True,
                        text=True,
                        timeout=max(1, int(timeout_seconds or 30)),
                        cwd=temp_dir,
                    )
                except subprocess.TimeoutExpired:
                    return json.dumps(
                        {
                            "success": False,
                            "error": f"Execucao excedeu o timeout de {timeout_seconds} segundos.",
                        },
                        ensure_ascii=False,
                    )

            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            result_text = None
            error_text = None
            for line in stdout.splitlines():
                if line.startswith("__CODEX_RESULT__="):
                    result_text = line.split("=", 1)[1]
                if line.startswith("__CODEX_ERROR__="):
                    error_text = line.split("=", 1)[1]

            clean_stdout = "\n".join(
                line for line in stdout.splitlines() if not line.startswith("__CODEX_RESULT__=") and not line.startswith("__CODEX_ERROR__=")
            ).strip()

            success = completed.returncode == 0 and not error_text
            return json.dumps(
                {
                    "success": success,
                    "returncode": completed.returncode,
                    "stdout": clean_stdout,
                    "stderr": stderr.strip(),
                    "result": result_text,
                    "error": error_text,
                },
                ensure_ascii=False,
            )

        return _tool
