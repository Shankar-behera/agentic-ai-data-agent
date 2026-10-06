"""Static validation of LLM-generated pandas code.

Static checks alone cannot make `exec` safe. They are one layer in front of the
subprocess sandbox in sandbox.py (empty environment, rlimits, timeout).
"""
import ast

from src.core.logging import get_logger

logger = get_logger(__name__)

ALLOWED_IMPORTS = frozenset({"pandas", "numpy", "math", "datetime"})

FORBIDDEN_NAMES = frozenset(
    {
        "eval", "exec", "compile", "open", "__import__", "input", "breakpoint", "globals", "locals",
        "vars", "dir", "getattr", "setattr", "delattr", "type", "memoryview", "help", "exit", "quit",
        "builtins", "super", "classmethod", "staticmethod", "property", "object",
    }
)

FORBIDDEN_ATTRS = frozenset(
    {
        # process / module access
        "system", "popen", "subprocess", "sh", "shell", "os", "sys", "importlib", "builtins", "io", "compat",
        "util", "testing", "ctypeslib", "f2py", "distutils",
        # dynamic evaluation
        "eval", "query", "style",
        # file / network IO
        "to_pickle", "to_csv", "to_json", "to_parquet", "to_excel", "to_sql", "to_hdf", "to_feather",
        "to_stata", "to_clipboard", "to_html", "to_latex", "to_markdown", "to_xml", "to_orc", "to_gbq",
        "load", "loads", "save", "savez", "savez_compressed", "savetxt", "fromfile", "tofile", "loadtxt",
        "genfromtxt", "memmap", "fromregex", "plot",
    }
)

FORBIDDEN_NODES = (
    ast.ClassDef, ast.AsyncFunctionDef, ast.Await, ast.Global, ast.Nonlocal, ast.AsyncFor, ast.AsyncWith,
    ast.Try, ast.TryStar,  # try/except lets generated code probe the sandbox quietly
)


class CodeValidator:
    def check(self, code: str) -> tuple[bool, str]:
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, f"Invalid Python code: {e}"

        for node in ast.walk(tree):
            if isinstance(node, FORBIDDEN_NODES):
                return False, f"Syntax not allowed: {type(node).__name__}"

            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] not in ALLOWED_IMPORTS:
                        return False, f"Import of '{alias.name}' is not allowed"
            elif isinstance(node, ast.ImportFrom):
                if node.level or (node.module or "").split(".")[0] not in ALLOWED_IMPORTS:
                    return False, f"Import from '{node.module}' is not allowed"

            elif isinstance(node, ast.Name):
                if node.id in FORBIDDEN_NAMES or node.id.startswith("__"):
                    return False, f"Use of '{node.id}' is not allowed"

            elif isinstance(node, ast.Attribute):
                # Any underscore-prefixed attribute (dunders and privates) is the usual escape route.
                if node.attr.startswith("_"):
                    return False, f"Access to '{node.attr}' is not allowed"
                if node.attr in FORBIDDEN_ATTRS or node.attr.startswith("read_"):
                    return False, f"Access to '.{node.attr}' is not allowed"

            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and "__" in node.value:
                return False, "Strings containing '__' are not allowed"

        return True, "ok"

    def validate(self, code: str) -> bool:
        ok, reason = self.check(code)
        if not ok:
            logger.warning("code_validation_failed", reason=reason)
        return ok
