import json

import pandas as pd
import pytest

from src.core.config import settings
from src.core.exceptions import ValidationError
from src.tools.etl import ETLTools


@pytest.fixture
def tools(tmp_path):
    return ETLTools(str(tmp_path / "data"))


class FakeResponse:
    def __init__(self, payload: bytes, status: int = 200):
        self._payload, self.status_code = payload, status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self._payload), chunk_size):
            yield self._payload[i : i + chunk_size]


@pytest.mark.parametrize("path", ["../../etc/passwd", "/etc/passwd", "a/../../b", "\x00x", ""])
def test_paths_cannot_escape_data_dir(tools, path):
    with pytest.raises(ValidationError):
        tools._confine(path)


def test_nested_relative_path_is_allowed(tools):
    assert tools._confine("extract/sub").is_relative_to(tools.base_dir)


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "ftp://pokeapi.co/x", "http://evil.example.com/x", "http://169.254.169.254/latest", "not a url"],
)
def test_url_validation_rejects_untrusted_targets(url):
    with pytest.raises(ValidationError):
        ETLTools.validate_url(url)


def test_allowlisted_host_resolving_to_private_ip_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "etl_allowed_hosts", ["internal.test"])
    monkeypatch.setattr("socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("10.0.0.5", 443))])
    with pytest.raises(ValidationError, match="non-public"):
        ETLTools.validate_url("https://internal.test/data")


def _allow(monkeypatch):
    monkeypatch.setattr(ETLTools, "validate_url", staticmethod(lambda u: u))


def test_extract_load_writes_inside_data_dir(tools, monkeypatch):
    _allow(monkeypatch)
    payload = json.dumps({"results": [{"a": 1}, {"a": 2}]}).encode()
    monkeypatch.setattr("requests.get", lambda *a, **k: FakeResponse(payload))
    res = tools.extract_load("https://pokeapi.co/x", "extract", "csv")
    assert res["status"] == "success" and res["rows"] == 2
    assert (tools.base_dir / "extract" / "extracted_data.csv").exists()


def test_extract_load_refuses_traversal_output_folder(tools, monkeypatch):
    _allow(monkeypatch)
    monkeypatch.setattr("requests.get", lambda *a, **k: FakeResponse(b"[]"))
    with pytest.raises(ValidationError):
        tools.extract_load("https://pokeapi.co/x", "../../tmp/evil", "csv")


def test_extract_load_enforces_download_cap(tools, monkeypatch):
    _allow(monkeypatch)
    monkeypatch.setattr(settings, "etl_max_download_mb", 0)
    monkeypatch.setattr("requests.get", lambda *a, **k: FakeResponse(b"[1,2,3]"))
    with pytest.raises(ValidationError, match="larger"):
        tools.extract_load("https://pokeapi.co/x", "extract", "csv")


def test_extract_load_rejects_unknown_format(tools):
    with pytest.raises(ValidationError):
        tools.extract_load("https://pokeapi.co/x", "extract", "exe")


def test_transform_context_rejects_files_outside_data_dir(tools):
    with pytest.raises(ValidationError):
        tools.transform_load_context("/etc/passwd")


def test_transform_end_to_end_via_sandbox(tools):
    (tools.base_dir / "in").mkdir()
    pd.DataFrame({"g": ["x", "x", "y"], "v": [1, 2, 3]}).to_csv(tools.base_dir / "in" / "d.csv", index=False)
    ctx = tools.transform_load_context("in/d.csv")
    assert ctx["rows"] == 3 and ctx["columns"] == ["g", "v"]
    ctx["output_format"] = "csv"
    res = tools.execute_pandas_code("result = df.groupby('g', as_index=False)['v'].sum()", ctx)
    assert res["status"] == "success" and res["rows"] == 2
    assert pd.read_csv(tools.base_dir / res["filename"]).to_dict("records") == [{"g": "x", "v": 3}, {"g": "y", "v": 3}]
