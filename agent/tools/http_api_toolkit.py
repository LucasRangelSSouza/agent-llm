import json
import logging
from typing import Any, Callable, Optional

import httpx

from agent.tools.sql_query_toolkit import SQLQueryToolkit


logger = logging.getLogger(__name__)


class HTTPAPIToolkit(SQLQueryToolkit):
    """
    Toolkit HTTP flexivel para integracoes externas.

    A secret vinculada ao agente pode ser resolvida por nome e injetada no
    request via placeholder.
    """

    def call_http_api(self) -> Callable[..., str]:
        def _tool(
            method: str,
            url: str,
            secret_name: Optional[str] = None,
            headers: Optional[Any] = None,
            body: Optional[Any] = None,
            params: Optional[Any] = None,
            timeout_seconds: float = 30.0,
            secret_placeholder: str = "{{secret}}",
        ) -> str:
            try:
                resolved_secret = self._find_linked_secret(secret_name or "") if secret_name else None
                secret_value = (resolved_secret or {}).get("value") or ""

                parsed_headers = self._parse_json_like(headers, expected_type=dict) or {}
                parsed_params = self._parse_json_like(params, expected_type=dict) or {}
                parsed_body = self._parse_json_like(body, expected_type=None)

                request_url = self._replace_secret(url, secret_placeholder, secret_value)
                request_headers = self._replace_secret(parsed_headers, secret_placeholder, secret_value)
                request_params = self._replace_secret(parsed_params, secret_placeholder, secret_value)
                request_body = self._replace_secret(parsed_body, secret_placeholder, secret_value)

                with httpx.Client(timeout=float(timeout_seconds), follow_redirects=True) as client:
                    response = client.request(
                        method=str(method or "GET").upper(),
                        url=request_url,
                        headers=request_headers or None,
                        params=request_params or None,
                        json=request_body if isinstance(request_body, (dict, list)) else None,
                        content=request_body if isinstance(request_body, str) else None,
                    )

                content_type = response.headers.get("content-type", "")
                body_json = None
                if "application/json" in content_type.lower():
                    try:
                        body_json = response.json()
                    except Exception:
                        body_json = None

                body_text = response.text
                if len(body_text) > 12000:
                    body_text = f"{body_text[:12000]}\n...[truncated]"

                return json.dumps(
                    {
                        "success": response.is_success,
                        "status_code": response.status_code,
                        "method": str(method or "GET").upper(),
                        "url": request_url,
                        "used_secret_name": (resolved_secret or {}).get("name"),
                        "response_headers": dict(response.headers),
                        "body_json": body_json,
                        "body_text": body_text,
                    },
                    ensure_ascii=False,
                    default=self._json_default,
                )
            except Exception as exc:
                logger.exception("Erro ao executar chamada HTTP externa.")
                return self._json_error(str(exc))

        return _tool

    def _parse_json_like(self, value: Any, expected_type: Optional[type]) -> Any:
        if value in (None, ""):
            return {} if expected_type is dict else None
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("{") or text.startswith("["):
                try:
                    parsed = json.loads(text)
                    if expected_type and not isinstance(parsed, expected_type):
                        raise ValueError(f"Valor precisa ser do tipo {expected_type.__name__}.")
                    return parsed
                except Exception:
                    if expected_type is dict:
                        raise ValueError("Nao foi possivel interpretar o JSON informado.")
            return value
        return value

    def _replace_secret(self, value: Any, placeholder: str, secret_value: str) -> Any:
        if not secret_value:
            return value
        if isinstance(value, str):
            return value.replace(placeholder, secret_value)
        if isinstance(value, dict):
            return {key: self._replace_secret(item, placeholder, secret_value) for key, item in value.items()}
        if isinstance(value, list):
            return [self._replace_secret(item, placeholder, secret_value) for item in value]
        return value
