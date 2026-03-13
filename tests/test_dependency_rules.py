import ast
from pathlib import Path


def test_dispatch_has_no_forbidden_imports():
    forbidden = ("bff", "frontend", "src.constraints", "src.pipeline")
    dispatch_root = Path("src/dispatch")

    for py_file in dispatch_root.rglob("*.py"):
      tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
      for node in ast.walk(tree):
          if isinstance(node, ast.Import):
              modules = [alias.name for alias in node.names]
          elif isinstance(node, ast.ImportFrom):
              modules = [node.module or ""]
          else:
              continue
          for module in modules:
              for prefix in forbidden:
                  assert not module.startswith(prefix), f"{py_file}: forbidden import '{module}'"
