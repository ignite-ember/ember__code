"""NotebookTools — Jupyter notebook cell editing."""

import json
from pathlib import Path
from typing import Any

from agno.tools import Toolkit


class NotebookTools(Toolkit):
    """Read and edit individual cells in Jupyter notebooks (.ipynb).

    Operates on the notebook's JSON structure directly — no nbformat
    dependency required. Preserves all metadata, outputs, and formatting.
    """

    def __init__(self, base_dir: str | None = None, **kwargs):
        super().__init__(name="ember_notebook", **kwargs)
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.register(self.notebook_read)
        self.register(self.notebook_read_cell)
        self.register(self.notebook_edit_cell)
        self.register(self.notebook_add_cell)
        self.register(self.notebook_remove_cell)

    def _resolve_path(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self.base_dir / p
        return p

    def _load_notebook(self, path: Path) -> dict | str:
        """Load a notebook, returning the dict or an error string."""
        if not path.exists():
            return f"Error: File not found: {path}"
        if path.suffix != ".ipynb":
            return f"Error: Not a notebook file: {path}"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return f"Error: Invalid notebook JSON: {e}"

    def _save_notebook(self, path: Path, nb: dict) -> None:
        path.write_text(
            json.dumps(nb, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _get_source(cell: dict) -> str:
        """Get cell source as a single string (handles list or string format)."""
        src = cell.get("source", "")
        if isinstance(src, list):
            return "".join(src)
        return src

    @staticmethod
    def _set_source(cell: dict, source: str) -> None:
        """Set cell source, preserving the original format (list vs string)."""
        original = cell.get("source", "")
        if isinstance(original, list):
            # Jupyter stores as list of lines, each ending with \n except the last
            lines = source.split("\n")
            cell["source"] = [line + "\n" for line in lines[:-1]] + [lines[-1]] if lines else []
        else:
            cell["source"] = source

    @staticmethod
    def _format_cell_summary(cell: dict, index: int) -> str:
        src = cell.get("source", "")
        if isinstance(src, list):
            src = "".join(src)
        cell_type = cell.get("cell_type", "unknown")
        preview = src[:120].replace("\n", "\\n")
        if len(src) > 120:
            preview += "..."
        lines = src.count("\n") + 1 if src else 0
        return f"[{index}] {cell_type} ({lines} lines): {preview}"

    @staticmethod
    def _make_cell(cell_type: str, source: str) -> dict:
        """Create a new notebook cell with proper nbformat 4 structure."""
        lines = source.split("\n")
        source_list = [line + "\n" for line in lines[:-1]] + [lines[-1]] if lines else []

        cell: dict[str, Any] = {
            "cell_type": cell_type,
            "metadata": {},
            "source": source_list,
        }
        if cell_type == "code":
            cell["execution_count"] = None
            cell["outputs"] = []
        return cell

    def notebook_read(self, file_path: str) -> str:
        """Read a Jupyter notebook and return a summary of all cells.

        Args:
            file_path: Path to the .ipynb file.

        Returns:
            Cell index, type, line count, and source preview for each cell.
        """
        path = self._resolve_path(file_path)
        nb = self._load_notebook(path)
        if isinstance(nb, str):
            return nb

        cells = nb.get("cells", [])
        if not cells:
            return f"Notebook {path} has no cells."

        kernel = nb.get("metadata", {}).get("kernelspec", {}).get("display_name", "unknown")
        lines = [f"Notebook: {path} ({len(cells)} cells, kernel: {kernel})", ""]
        for i, cell in enumerate(cells):
            lines.append(self._format_cell_summary(cell, i))
        return "\n".join(lines)

    def notebook_read_cell(self, file_path: str, cell_index: int) -> str:
        """Read a specific cell's full source and outputs.

        Args:
            file_path: Path to the .ipynb file.
            cell_index: Zero-based index of the cell to read.

        Returns:
            Cell type, full source, and outputs (for code cells).
        """
        path = self._resolve_path(file_path)
        nb = self._load_notebook(path)
        if isinstance(nb, str):
            return nb

        cells = nb.get("cells", [])
        if cell_index < 0 or cell_index >= len(cells):
            return f"Error: Cell index {cell_index} out of range (0-{len(cells) - 1})."

        cell = cells[cell_index]
        cell_type = cell.get("cell_type", "unknown")
        source = self._get_source(cell)

        parts = [f"Cell [{cell_index}] ({cell_type}):", "", source]

        if cell_type == "code":
            outputs = cell.get("outputs", [])
            if outputs:
                parts.append("")
                parts.append(f"--- Outputs ({len(outputs)}) ---")
                for out in outputs:
                    out_type = out.get("output_type", "unknown")
                    if out_type == "stream":
                        text = "".join(out.get("text", []))
                        parts.append(f"[stream/{out.get('name', 'stdout')}] {text[:500]}")
                    elif out_type in ("execute_result", "display_data"):
                        data = out.get("data", {})
                        if "text/plain" in data:
                            text = "".join(data["text/plain"])
                            parts.append(f"[{out_type}] {text[:500]}")
                        else:
                            parts.append(f"[{out_type}] keys: {list(data.keys())}")
                    elif out_type == "error":
                        parts.append(f"[error] {out.get('ename', '')}: {out.get('evalue', '')}")

        return "\n".join(parts)

    def notebook_edit_cell(self, file_path: str, cell_index: int, new_source: str) -> str:
        """Replace a cell's source content.

        Clears outputs for code cells (standard Jupyter behavior for modified cells).

        Args:
            file_path: Path to the .ipynb file.
            cell_index: Zero-based index of the cell to edit.
            new_source: The new source content for the cell.

        Returns:
            Success or error message.
        """
        path = self._resolve_path(file_path)
        nb = self._load_notebook(path)
        if isinstance(nb, str):
            return nb

        cells = nb.get("cells", [])
        if cell_index < 0 or cell_index >= len(cells):
            return f"Error: Cell index {cell_index} out of range (0-{len(cells) - 1})."

        cell = cells[cell_index]
        self._set_source(cell, new_source)

        # Clear outputs for modified code cells
        if cell.get("cell_type") == "code":
            cell["outputs"] = []
            cell["execution_count"] = None

        self._save_notebook(path, nb)
        return f"Successfully edited cell [{cell_index}] in {path}"

    def notebook_add_cell(
        self, file_path: str, cell_index: int, cell_type: str, source: str
    ) -> str:
        """Insert a new cell at the given index.

        Args:
            file_path: Path to the .ipynb file.
            cell_index: Position to insert at (0 = beginning). Use -1 to append.
            cell_type: One of "code", "markdown", or "raw".
            source: The cell source content.

        Returns:
            Success or error message.
        """
        if cell_type not in ("code", "markdown", "raw"):
            return f"Error: Invalid cell_type '{cell_type}'. Must be 'code', 'markdown', or 'raw'."

        path = self._resolve_path(file_path)
        nb = self._load_notebook(path)
        if isinstance(nb, str):
            return nb

        cells = nb.get("cells", [])
        new_cell = self._make_cell(cell_type, source)

        if cell_index == -1:
            cells.append(new_cell)
            idx = len(cells) - 1
        else:
            if cell_index < 0 or cell_index > len(cells):
                return f"Error: Cell index {cell_index} out of range (0-{len(cells)})."
            cells.insert(cell_index, new_cell)
            idx = cell_index

        nb["cells"] = cells
        self._save_notebook(path, nb)
        return f"Successfully added {cell_type} cell at [{idx}] in {path}"

    def notebook_remove_cell(self, file_path: str, cell_index: int) -> str:
        """Remove a cell by index.

        Args:
            file_path: Path to the .ipynb file.
            cell_index: Zero-based index of the cell to remove.

        Returns:
            Success or error message.
        """
        path = self._resolve_path(file_path)
        nb = self._load_notebook(path)
        if isinstance(nb, str):
            return nb

        cells = nb.get("cells", [])
        if cell_index < 0 or cell_index >= len(cells):
            return f"Error: Cell index {cell_index} out of range (0-{len(cells) - 1})."

        removed = cells.pop(cell_index)
        nb["cells"] = cells
        self._save_notebook(path, nb)
        return f"Successfully removed {removed.get('cell_type', 'unknown')} cell [{cell_index}] from {path}"
