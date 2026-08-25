# Consolidated interface component node — supports both HTML and JSX/React modes.
# HTML mode: renders raw HTML content with SDK access (no transpilation).
# JSX mode: transpiles React/JSX via Sucrase, auto-resolves npm packages, includes Tailwind CSS.

import logging
from typing import Any, Dict, Literal, Optional, Type, Union

from pydantic import BaseModel, Discriminator, Field, Tag, field_validator
from typing_extensions import Annotated

from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)

DEFAULT_JSX = """import React, { useState } from 'react';
import ReactDOM from 'react-dom/client';

function App() {
  const [count, setCount] = useState(0);

  return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-4 p-4">
      <h1 className="text-2xl font-bold text-white">Custom Component</h1>
      <p className="text-zinc-400">Count: {count}</p>
      <button
        className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-500"
        onClick={() => setCount(c => c + 1)}
      >
        Increment
      </button>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
"""


class HtmlOperationConfig(BaseModel):
    """Configuration for HTML mode."""

    model_config = {"title": "HTML"}
    operation: Literal["render_html_interface"] = Field(
        "render_html_interface",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "General",
            "x-is-trigger": False,
            "x-display-name": "Render HTML",
        },
        title="Render HTML",
    )
    content: str = Field(
        default="",
        title="Content",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "html"},
    )
    fullscreen: str = Field(
        "true",
        title="Fullscreen",
        description="Show as a fullscreen tab instead of in the grid layout",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )

    @field_validator("fullscreen", mode="before")
    @classmethod
    def coerce_fullscreen(cls, v: Any) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        return str(v)


class JsxOperationConfig(BaseModel):
    """Configuration for JSX/React mode."""

    model_config = {"title": "JSX / React"}
    operation: Literal["render_jsx_react_interface"] = Field(
        "render_jsx_react_interface",
        json_schema_extra={
            "ui:hidden": True,
            "x-category": "General",
            "x-is-trigger": False,
            "x-display-name": "Render React/JSX",
        },
        title="Render React/JSX",
    )
    jsx_source: str = Field(
        default=DEFAULT_JSX,
        title="JSX Source",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "jsx"},
    )
    fullscreen: str = Field(
        "true",
        title="Fullscreen",
        description="Show as a fullscreen tab instead of in the grid layout",
        json_schema_extra={
            "enum": ["true", "false"],
            "enumNames": ["Yes", "No"],
            "x-enum-searchable": True,
        },
    )

    @field_validator("fullscreen", mode="before")
    @classmethod
    def coerce_fullscreen(cls, v: Any) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        return str(v)


HtmlReactConfig = Annotated[
    Union[
        Annotated[HtmlOperationConfig, Tag("html")],
        Annotated[JsxOperationConfig, Tag("jsx")],
    ],
    Discriminator("operation"),
]


class HtmlReactInterfaceNodeConfig(NodeConfig[HtmlReactConfig, None]):
    """Full configuration for the consolidated component interface node."""

    pass


class HtmlReactInterfaceNode(WorkflowNode):
    """Interface component node — renders HTML or JSX/React components with SDK access."""

    connectionless = True
    grid_layout = {"defaultW": 6, "defaultH": 4, "minW": 3, "minH": 2}
    edit_examples = [
        "Switch from HTML mode to JSX/React mode",
        "Add interactive buttons and event handlers",
        "Embed a custom React component with state",
        "Import an npm package for the component",
        "Make the component fullscreen instead",
        "Style with TailwindCSS utility classes",
    ]

    @classmethod
    def get_config_model(cls) -> Optional[Type]:
        return HtmlReactInterfaceNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        config = self._config.config if self._config else HtmlOperationConfig()
        operation = getattr(config, "operation", "html")

        if operation == "render_jsx_react_interface":
            return await self._execute_jsx(config, inputs)
        else:
            return await self._execute_html(config, inputs)

    async def _execute_html(
        self, config: HtmlOperationConfig, inputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """HTML mode: wrap content with SDK import map and auto-detected npm packages."""
        content = inputs.get("value", inputs.get("content", config.content))

        from utils.jsx_transpiler import (
            _load_sdk_bundle,
            extract_imports,
            ESM_SH,
            REACT_VERSION,
            EXTERNAL,
            TAILWIND_CDN,
        )
        import base64
        import json

        # Build import map with React, SDK, and auto-detected npm packages
        imports = {
            "react": f"{ESM_SH}/react@{REACT_VERSION}",
            "react/": f"{ESM_SH}/react@{REACT_VERSION}/",
            "react-dom": f"{ESM_SH}/react-dom@{REACT_VERSION}?external={EXTERNAL}",
            "react-dom/": f"{ESM_SH}/react-dom@{REACT_VERSION}&external={EXTERNAL}/",
            "react/jsx-runtime": f"{ESM_SH}/react@{REACT_VERSION}/jsx-runtime",
        }
        try:
            sdk_js = _load_sdk_bundle()
            encoded = base64.b64encode(sdk_js.encode()).decode()
            imports["@noclick/sdk"] = f"data:text/javascript;base64,{encoded}"
        except FileNotFoundError:
            pass

        # Auto-detect npm packages from <script type="module"> content
        packages = extract_imports(content)
        for pkg in sorted(packages):
            imports[pkg] = f"{ESM_SH}/{pkg}?external={EXTERNAL}&bundle"
            if pkg.startswith("@"):
                imports[f"{pkg}/"] = f"{ESM_SH}/{pkg}&external={EXTERNAL}&bundle/"

        import_map_json = json.dumps({"imports": imports}, indent=2)

        srcdoc = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <script type="importmap">
{import_map_json}
  </script>
  <script src="{TAILWIND_CDN}"></script>
  <style>
    body {{ margin: 0; padding: 8px; font-family: system-ui, sans-serif; background: transparent; color: #d4d4d8; font-size: 13px; }}
  </style>
</head>
<body>{content}</body>
</html>"""

        output = {
            "content": content,
            "srcdoc": srcdoc,
            "type": "component",
            "operation": "render_html_interface",
        }
        await self.emit(output)
        return output

    async def _execute_jsx(
        self, config: JsxOperationConfig, inputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """JSX mode: transpile via Sucrase, build import map, assemble srcdoc."""
        from utils.jsx_transpiler import build_component

        jsx_source = inputs.get("value", inputs.get("jsx_source", config.jsx_source))

        result = build_component(jsx_source)
        if not result.success:
            error_output = {
                "type": "component",
                "operation": "render_jsx_react_interface",
                "error": result.error,
                "srcdoc": "",
            }
            await self.emit(error_output)
            return error_output

        output = {
            "type": "component",
            "operation": "render_jsx_react_interface",
            "srcdoc": result.srcdoc,
        }
        await self.emit(output)
        return output
