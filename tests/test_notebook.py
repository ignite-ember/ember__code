"""Tests for tools/notebook.py — Jupyter notebook cell editing."""

import json

from ember_code.tools.notebook import NotebookTools


def _make_notebook(cells=None, kernel="python3"):
    """Create a minimal valid notebook dict."""
    return {
        "cells": cells or [],
        "metadata": {
            "kernelspec": {
                "display_name": kernel,
                "language": "python",
                "name": "python3",
            }
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def _code_cell(source, outputs=None):
    lines = source.split("\n")
    src_list = [line + "\n" for line in lines[:-1]] + [lines[-1]] if lines else []
    return {
        "cell_type": "code",
        "source": src_list,
        "metadata": {},
        "execution_count": 1,
        "outputs": outputs or [],
    }


def _md_cell(source):
    return {
        "cell_type": "markdown",
        "source": source,
        "metadata": {},
    }


def _write_notebook(path, nb):
    path.write_text(json.dumps(nb, indent=1))


class TestNotebookRead:
    def test_reads_notebook_summary(self, tmp_path):
        nb = _make_notebook([_code_cell("x = 1"), _md_cell("# Title")])
        path = tmp_path / "test.ipynb"
        _write_notebook(path, nb)

        tools = NotebookTools(base_dir=str(tmp_path))
        result = tools.notebook_read("test.ipynb")

        assert "2 cells" in result
        assert "[0] code" in result
        assert "[1] markdown" in result
        assert "x = 1" in result

    def test_reads_empty_notebook(self, tmp_path):
        nb = _make_notebook([])
        path = tmp_path / "empty.ipynb"
        _write_notebook(path, nb)

        tools = NotebookTools(base_dir=str(tmp_path))
        result = tools.notebook_read("empty.ipynb")
        assert "no cells" in result.lower()

    def test_error_on_missing_file(self, tmp_path):
        tools = NotebookTools(base_dir=str(tmp_path))
        result = tools.notebook_read("missing.ipynb")
        assert "Error" in result

    def test_error_on_non_notebook(self, tmp_path):
        (tmp_path / "test.py").write_text("x = 1")
        tools = NotebookTools(base_dir=str(tmp_path))
        result = tools.notebook_read("test.py")
        assert "Error" in result


class TestNotebookReadCell:
    def test_reads_code_cell(self, tmp_path):
        nb = _make_notebook([_code_cell("print('hello')")])
        path = tmp_path / "test.ipynb"
        _write_notebook(path, nb)

        tools = NotebookTools(base_dir=str(tmp_path))
        result = tools.notebook_read_cell("test.ipynb", 0)
        assert "print('hello')" in result
        assert "code" in result

    def test_reads_markdown_cell(self, tmp_path):
        nb = _make_notebook([_md_cell("# Hello")])
        path = tmp_path / "test.ipynb"
        _write_notebook(path, nb)

        tools = NotebookTools(base_dir=str(tmp_path))
        result = tools.notebook_read_cell("test.ipynb", 0)
        assert "# Hello" in result
        assert "markdown" in result

    def test_shows_outputs(self, tmp_path):
        outputs = [{"output_type": "stream", "name": "stdout", "text": ["hello\n"]}]
        nb = _make_notebook([_code_cell("print('hello')", outputs=outputs)])
        path = tmp_path / "test.ipynb"
        _write_notebook(path, nb)

        tools = NotebookTools(base_dir=str(tmp_path))
        result = tools.notebook_read_cell("test.ipynb", 0)
        assert "hello" in result
        assert "Outputs" in result

    def test_error_on_invalid_index(self, tmp_path):
        nb = _make_notebook([_code_cell("x = 1")])
        path = tmp_path / "test.ipynb"
        _write_notebook(path, nb)

        tools = NotebookTools(base_dir=str(tmp_path))
        result = tools.notebook_read_cell("test.ipynb", 5)
        assert "Error" in result
        assert "out of range" in result


class TestNotebookEditCell:
    def test_edits_cell_source(self, tmp_path):
        nb = _make_notebook([_code_cell("x = 1"), _code_cell("y = 2")])
        path = tmp_path / "test.ipynb"
        _write_notebook(path, nb)

        tools = NotebookTools(base_dir=str(tmp_path))
        result = tools.notebook_edit_cell("test.ipynb", 0, "x = 42")
        assert "Successfully edited" in result

        # Verify only cell 0 changed
        edited = json.loads(path.read_text())
        src0 = "".join(edited["cells"][0]["source"])
        src1 = "".join(edited["cells"][1]["source"])
        assert src0 == "x = 42"
        assert src1 == "y = 2"

    def test_clears_outputs_on_edit(self, tmp_path):
        outputs = [{"output_type": "stream", "name": "stdout", "text": ["1\n"]}]
        nb = _make_notebook([_code_cell("x = 1", outputs=outputs)])
        path = tmp_path / "test.ipynb"
        _write_notebook(path, nb)

        tools = NotebookTools(base_dir=str(tmp_path))
        tools.notebook_edit_cell("test.ipynb", 0, "x = 2")

        edited = json.loads(path.read_text())
        assert edited["cells"][0]["outputs"] == []
        assert edited["cells"][0]["execution_count"] is None

    def test_preserves_metadata(self, tmp_path):
        nb = _make_notebook([_code_cell("x = 1")])
        nb["metadata"]["custom"] = "value"
        path = tmp_path / "test.ipynb"
        _write_notebook(path, nb)

        tools = NotebookTools(base_dir=str(tmp_path))
        tools.notebook_edit_cell("test.ipynb", 0, "x = 2")

        edited = json.loads(path.read_text())
        assert edited["metadata"]["custom"] == "value"
        assert edited["nbformat"] == 4


class TestNotebookAddCell:
    def test_adds_cell_at_beginning(self, tmp_path):
        nb = _make_notebook([_code_cell("x = 1")])
        path = tmp_path / "test.ipynb"
        _write_notebook(path, nb)

        tools = NotebookTools(base_dir=str(tmp_path))
        result = tools.notebook_add_cell("test.ipynb", 0, "markdown", "# New")
        assert "Successfully added" in result

        edited = json.loads(path.read_text())
        assert len(edited["cells"]) == 2
        assert edited["cells"][0]["cell_type"] == "markdown"

    def test_appends_cell(self, tmp_path):
        nb = _make_notebook([_code_cell("x = 1")])
        path = tmp_path / "test.ipynb"
        _write_notebook(path, nb)

        tools = NotebookTools(base_dir=str(tmp_path))
        result = tools.notebook_add_cell("test.ipynb", -1, "code", "y = 2")
        assert "Successfully added" in result

        edited = json.loads(path.read_text())
        assert len(edited["cells"]) == 2
        src = "".join(edited["cells"][1]["source"])
        assert src == "y = 2"

    def test_code_cell_has_outputs_field(self, tmp_path):
        nb = _make_notebook([])
        path = tmp_path / "test.ipynb"
        _write_notebook(path, nb)

        tools = NotebookTools(base_dir=str(tmp_path))
        tools.notebook_add_cell("test.ipynb", 0, "code", "x = 1")

        edited = json.loads(path.read_text())
        assert "outputs" in edited["cells"][0]
        assert "execution_count" in edited["cells"][0]

    def test_error_on_invalid_type(self, tmp_path):
        nb = _make_notebook([])
        path = tmp_path / "test.ipynb"
        _write_notebook(path, nb)

        tools = NotebookTools(base_dir=str(tmp_path))
        result = tools.notebook_add_cell("test.ipynb", 0, "invalid", "x")
        assert "Error" in result


class TestNotebookRemoveCell:
    def test_removes_cell(self, tmp_path):
        nb = _make_notebook([_code_cell("x = 1"), _code_cell("y = 2"), _code_cell("z = 3")])
        path = tmp_path / "test.ipynb"
        _write_notebook(path, nb)

        tools = NotebookTools(base_dir=str(tmp_path))
        result = tools.notebook_remove_cell("test.ipynb", 1)
        assert "Successfully removed" in result

        edited = json.loads(path.read_text())
        assert len(edited["cells"]) == 2
        src0 = "".join(edited["cells"][0]["source"])
        src1 = "".join(edited["cells"][1]["source"])
        assert src0 == "x = 1"
        assert src1 == "z = 3"

    def test_error_on_invalid_index(self, tmp_path):
        nb = _make_notebook([_code_cell("x = 1")])
        path = tmp_path / "test.ipynb"
        _write_notebook(path, nb)

        tools = NotebookTools(base_dir=str(tmp_path))
        result = tools.notebook_remove_cell("test.ipynb", 5)
        assert "Error" in result
