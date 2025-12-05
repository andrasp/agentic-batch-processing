"""Tests for enumerators."""

import pytest
import tempfile
import os
from pathlib import Path

from agentic_batch_processor.enumerators import create_enumerator, get_all_enumerator_schemas
from agentic_batch_processor.enumerators.file_enumerator import FileEnumerator
from agentic_batch_processor.enumerators.csv_enumerator import CsvEnumerator
from agentic_batch_processor.enumerators.json_enumerator import JsonEnumerator


class TestEnumeratorRegistry:
    """Tests for enumerator registry."""

    def test_create_file_enumerator(self):
        """create_enumerator creates FileEnumerator for 'file' type."""
        enumerator = create_enumerator("file", {"base_directory": "/tmp", "pattern": "*.txt"})
        assert isinstance(enumerator, FileEnumerator)

    def test_create_csv_enumerator(self):
        """create_enumerator creates CsvEnumerator for 'csv' type."""
        enumerator = create_enumerator("csv", {"file_path": "/tmp/test.csv"})
        assert isinstance(enumerator, CsvEnumerator)

    def test_create_json_enumerator(self):
        """create_enumerator creates JsonEnumerator for 'json' type."""
        enumerator = create_enumerator("json", {"file_path": "/tmp/test.json"})
        assert isinstance(enumerator, JsonEnumerator)

    def test_create_unknown_type_raises(self):
        """create_enumerator raises ValueError for unknown type."""
        with pytest.raises(ValueError, match="Unknown enumerator type"):
            create_enumerator("unknown_type", {})

    def test_get_all_enumerator_schemas(self):
        """get_all_enumerator_schemas returns schemas for all types."""
        schemas = get_all_enumerator_schemas()

        assert "file" in schemas
        assert "csv" in schemas
        assert "json" in schemas
        assert "sql" in schemas
        assert "dynamic" in schemas


class TestFileEnumerator:
    """Tests for FileEnumerator."""

    def test_enumerate_files(self):
        """FileEnumerator finds files matching pattern."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "test1.txt").touch()
            Path(tmpdir, "test2.txt").touch()
            Path(tmpdir, "other.md").touch()

            enumerator = FileEnumerator({"base_directory": tmpdir, "pattern": "*.txt"})
            result = enumerator.enumerate()

            assert result.success
            assert len(result.items) == 2
            assert all("file_path" in item for item in result.items)

    def test_enumerate_empty_directory(self):
        """FileEnumerator returns empty list for no matches."""
        with tempfile.TemporaryDirectory() as tmpdir:
            enumerator = FileEnumerator({"base_directory": tmpdir, "pattern": "*.nonexistent"})
            result = enumerator.enumerate()

            assert result.success
            assert len(result.items) == 0

    def test_validate_config_nonexistent_directory(self):
        """FileEnumerator validates nonexistent base_directory."""
        enumerator = FileEnumerator({"base_directory": "/nonexistent/path/xyz", "pattern": "*.txt"})
        error = enumerator.validate_config()
        assert error is not None
        assert "does not exist" in error.lower()


class TestCsvEnumerator:
    """Tests for CsvEnumerator."""

    def test_enumerate_csv_rows(self):
        """CsvEnumerator reads CSV rows as items."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("name,value\n")
            f.write("item1,100\n")
            f.write("item2,200\n")
            f.flush()

            try:
                enumerator = CsvEnumerator({"file_path": f.name})
                result = enumerator.enumerate()

                assert result.success
                assert len(result.items) == 2
                assert result.items[0]["name"] == "item1"
                assert result.items[1]["value"] == "200"
            finally:
                os.unlink(f.name)


class TestJsonEnumerator:
    """Tests for JsonEnumerator."""

    def test_enumerate_json_array(self):
        """JsonEnumerator reads JSON array items."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('[{"id": 1, "name": "first"}, {"id": 2, "name": "second"}]')
            f.flush()

            try:
                enumerator = JsonEnumerator({"file_path": f.name})
                result = enumerator.enumerate()

                assert result.success
                assert len(result.items) == 2
                assert result.items[0]["id"] == 1
                assert result.items[1]["name"] == "second"
            finally:
                os.unlink(f.name)

    def test_enumerate_json_with_path(self):
        """JsonEnumerator extracts items from nested path."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"data": {"items": [{"x": 1}, {"x": 2}]}}')
            f.flush()

            try:
                enumerator = JsonEnumerator({"file_path": f.name, "items_path": "data.items"})
                result = enumerator.enumerate()

                assert result.success
                assert len(result.items) == 2
            finally:
                os.unlink(f.name)
