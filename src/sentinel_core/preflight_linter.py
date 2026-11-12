"""Sentinel Pre-Flight Deterministic Rewriter & AST Linter (Upgrade A).
Executes in < 2ms before sandbox/AppContainer launch to catch known breaking API traps
and deterministically rewrite them, saving heavy subprocess cycles.
"""
from __future__ import annotations

import ast
import re
import textwrap
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PreFlightResult:
    code: str
    modified: bool = False
    fatal_error: str | None = None
    applied_fixes: list[str] = field(default_factory=list)


class PreFlightLinter:
    """Ultra-fast deterministic sanitizer and linter."""

    @classmethod
    def sanitize(cls, code: str, domain: str) -> PreFlightResult:
        """Sanitizes code in < 2ms based on domain invariants."""
        if domain == "3d":
            return cls._sanitize_blender(code)
        elif domain == "code":
            return cls._sanitize_python(code)
        elif domain == "data":
            return cls._sanitize_data(code)
        return PreFlightResult(code=code, modified=False)

    @classmethod
    def _sanitize_blender(cls, code: str) -> PreFlightResult:
        applied = []
        modified_code = textwrap.dedent(code).strip()
        if modified_code != code:
            applied.append("Dedented leading whitespace from generated script")

        # 1. Syntax check first with truncation self-repair
        try:
            ast.parse(modified_code)
        except SyntaxError as e:
            # Check if trimming truncated incomplete tail lines heals the script
            lines = modified_code.splitlines()
            healed = False
            for _ in range(min(5, len(lines))):
                lines.pop()
                test_code = "\n".join(lines).strip()
                try:
                    ast.parse(test_code)
                    modified_code = test_code
                    applied.append("Healed truncated trailing syntax error from token limit")
                    healed = True
                    break
                except SyntaxError:
                    continue
            if not healed:
                return PreFlightResult(
                    code=code,
                    modified=False,
                    fatal_error=f"SyntaxError in generated script: {e.msg} at line {e.lineno}",
                )

        # 1b. Fix unassigned obj_data variable references
        if "obj_data.materials" in modified_code and "obj_data =" not in modified_code:
            modified_code = re.sub(
                r"\bobj_data\.materials\.append\b",
                "bpy.context.active_object.data.materials.append",
                modified_code,
            )
            applied.append("Sanitized undefined obj_data to bpy.context.active_object.data")

        # 1c. Auto-link unlinked bpy.data.objects.new calls
        # If an object is created with bpy.data.objects.new, ensure it is linked to the collection.
        # Crucially: do NOT comment out the variable assignment as that causes downstream NameError.
        if "bpy.data.objects.new" in modified_code and ".link(" not in modified_code:
            def _link_repl(match):
                var_name = match.group(1)
                full_stmt = match.group(0)
                return f"{full_stmt}\nbpy.context.collection.objects.link({var_name})"

            modified_code = re.sub(
                r"^\s*(\w+)\s*=\s*bpy\.data\.objects\.new\(.*?\)\s*$",
                _link_repl,
                modified_code,
                flags=re.MULTILINE,
            )
            applied.append("Auto-linked newly created bpy.data.objects.new object to active collection")

        # 2. Blender 4.0+ Export Operator rewrite
        # bpy.ops.export_scene.obj(filepath=...) -> bpy.ops.wm.obj_export(filepath=...)
        if "bpy.ops.export_scene.obj" in modified_code:
            modified_code = re.sub(
                r"bpy\.ops\.export_scene\.obj\s*\(",
                "bpy.ops.wm.obj_export(",
                modified_code,
            )
            applied.append("Rewrote deprecated 'bpy.ops.export_scene.obj' to 'bpy.ops.wm.obj_export'")

        # 3. Principled BSDF 'Specular' float input in Blender 4.0+
        # In Blender 4.0+, Principled BSDF removed the scalar 'Specular' input
        if ".inputs['Specular']" in modified_code or '.inputs["Specular"]' in modified_code:
            modified_code = re.sub(
                r"(\w+)\.inputs\[['\"]Specular['\"]\]\.default_value\s*=\s*[\d\.]+",
                r"# \g<0> (Auto-disabled: Specular input removed in Blender 4.0+)",
                modified_code,
            )
            applied.append("Sanitized deprecated Principled BSDF Specular input")

        # 4. Check/inject scene reset if missing
        if "bpy.ops.wm.read_factory_settings" not in modified_code:
            init_call = "import bpy\nbpy.ops.wm.read_factory_settings(use_empty=True)\n"
            if "import bpy" in modified_code:
                modified_code = modified_code.replace("import bpy", init_call, 1)
            else:
                modified_code = init_call + modified_code
            applied.append("Injected missing 'bpy.ops.wm.read_factory_settings(use_empty=True)'")

        return PreFlightResult(
            code=modified_code,
            modified=len(applied) > 0,
            applied_fixes=applied,
        )

    @classmethod
    def _sanitize_python(cls, code: str) -> PreFlightResult:
        applied = []
        modified_code = code

        # 1. Fast AST syntax check
        try:
            ast.parse(modified_code)
        except SyntaxError as e:
            return PreFlightResult(
                code=code,
                modified=False,
                fatal_error=f"SyntaxError: {e.msg} at line {e.lineno}",
            )

        # 2. Pattern fix: popitem followed immediately by redundant del self.cache[...]
        pattern = re.compile(
            r"(\s*)(\w+),\s*_\s*=\s*([\w\.]+)\.popitem\(last=False\)\s*\n\s*del\s+\3\[\2\]",
            re.MULTILINE,
        )
        if pattern.search(modified_code):
            modified_code = pattern.sub(
                r"\1\2, _ = \3.popitem(last=False)  # Redundant del auto-removed by Sentinel PreFlight",
                modified_code,
            )
            applied.append("Removed redundant 'del' after popitem() to prevent KeyError")

        return PreFlightResult(
            code=modified_code,
            modified=len(applied) > 0,
            applied_fixes=applied,
        )

    @classmethod
    def _sanitize_data(cls, text: str) -> PreFlightResult:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        clean_lines = [l for l in lines if not l.startswith("```")]
        cleaned = "\n".join(clean_lines)
        modified = len(clean_lines) != len(lines)
        return PreFlightResult(
            code=cleaned,
            modified=modified,
            applied_fixes=["Stripped Markdown fences from raw CSV data"] if modified else [],
        )
