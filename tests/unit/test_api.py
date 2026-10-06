import threading
import time

import pytest
from fastapi.testclient import TestClient

from src.agents.data_agent import DataAgent, get_data_agent
from src.api import dependencies
from src.core.config import Settings, settings
from src.core.exceptions import ConfigurationError
from src.main import app
from tests.conftest import FakeLLM


class StubAgent:
    def __init__(self, result=None, exc=None, gate=None):
        self.result = result or {"success": True, "answer": "42", "route": "sql", "sql": "SELECT 42", "error": None}
        self.exc, self.gate = exc, gate

    def invoke(self, question):
        if self.gate:
            self.gate.wait(5)
        if self.exc:
            raise self.exc
        return self.result


@pytest.fixture
def client():
    dependencies.limiter.reset()
    c = TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides[get_data_agent] = lambda: StubAgent()
    yield c
    app.dependency_overrides.clear()


def test_health_needs_no_backends(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "healthy"


def test_app_imports_and_serves_without_ollama_or_postgres(client):
    # Regression: agents used to be built at import time and crashed the whole app when Ollama was down.
    assert client.get("/").status_code == 200


def test_query_ok(client):
    r = client.post("/api/v1/query", json={"question": "hi"})
    body = r.json()
    assert r.status_code == 200 and body["answer"] == "42" and body["sql"] == "SELECT 42" and body["agent_type"] == "sql"


def test_request_id_is_generated_and_echoed(client):
    assert len(client.get("/health").headers["x-request-id"]) >= 8
    assert client.get("/health", headers={"X-Request-ID": "abcdef123456"}).headers["x-request-id"] == "abcdef123456"
    assert client.get("/health", headers={"X-Request-ID": "bad id\r\n"}).headers["x-request-id"] != "bad id"


@pytest.mark.parametrize("payload", [{}, {"question": ""}, {"question": "x" * 10_000}, {"question": "q", "session_id": "../../x"}])
def test_query_validation(client, payload):
    assert client.post("/api/v1/query", json=payload).status_code == 422


def test_api_key_enforced_when_configured(client, monkeypatch):
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "api_key", SecretStr("s3cret-key"))
    assert client.post("/api/v1/query", json={"question": "q"}).status_code == 401
    assert client.post("/api/v1/query", json={"question": "q"}, headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.post("/api/v1/query", json={"question": "q"}, headers={"X-API-Key": "s3cret-key"}).status_code == 200
    assert client.get("/health").status_code == 200  # probes stay open


def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_minute", 2)
    codes = [client.post("/api/v1/query", json={"question": "q"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    assert "retry-after" in client.post("/api/v1/query", json={"question": "q"}).headers


def test_concurrency_cap_returns_429_instead_of_queueing_forever(client, monkeypatch):
    monkeypatch.setattr(dependencies, "_query_slots", threading.BoundedSemaphore(1))
    monkeypatch.setattr(settings, "queue_timeout_s", 0.2)
    gate = threading.Event()
    app.dependency_overrides[get_data_agent] = lambda: StubAgent(gate=gate)
    results = []
    t = threading.Thread(target=lambda: results.append(client.post("/api/v1/query", json={"question": "slow"}).status_code))
    t.start()
    time.sleep(0.3)
    assert client.post("/api/v1/query", json={"question": "second"}).status_code == 429
    gate.set()
    t.join(5)
    assert results == [200]


def test_health_stays_fast_while_a_query_is_running(client):
    gate = threading.Event()
    app.dependency_overrides[get_data_agent] = lambda: StubAgent(gate=gate)
    t = threading.Thread(target=lambda: client.post("/api/v1/query", json={"question": "slow"}))
    t.start()
    time.sleep(0.3)
    started = time.perf_counter()
    assert client.get("/health").status_code == 200
    assert time.perf_counter() - started < 1.0  # was 6.6s when the route blocked the event loop
    gate.set()
    t.join(5)


def test_unhandled_error_does_not_leak_internals(client):
    app.dependency_overrides[get_data_agent] = lambda: StubAgent(exc=RuntimeError("password=hunter2 at /srv/app.py"))
    r = client.post("/api/v1/query", json={"question": "q"})
    assert r.status_code == 500 and "hunter2" not in r.text and r.json()["request_id"]


def test_ready_reports_each_component(client, monkeypatch):
    import src.main as main

    monkeypatch.setattr(main._probe_db, "ping", lambda: True)
    monkeypatch.setattr(main, "create_llm_provider", lambda: FakeLLM([]))
    assert client.get("/ready").json() == {"ready": True, "components": {"database": True, "ollama": True, "model": True}}
    monkeypatch.setattr(main._probe_db, "ping", lambda: False)
    r = client.get("/ready")
    assert r.status_code == 503 and r.json()["components"]["database"] is False


def test_upload_roundtrip_and_validation(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    ok = client.post("/api/v1/upload", files={"file": ("../../evil name.csv", b"a,b\n1,2\n3,4\n")})
    body = ok.json()
    assert ok.status_code == 200 and body["rows"] == 2 and body["columns"] == ["a", "b"]
    assert "/" not in body["filename"] and len(list((tmp_path / "uploads").iterdir())) == 1
    assert client.post("/api/v1/upload", files={"file": ("x.exe", b"MZ")}).status_code == 400
    monkeypatch.setattr(settings, "max_upload_size_mb", 0)
    assert client.post("/api/v1/upload", files={"file": ("big.csv", b"a\n1\n")}).status_code == 400
    assert len(list((tmp_path / "uploads").iterdir())) == 1  # the oversized file was removed


def test_data_agent_end_to_end_with_stub_subagents(fake_llm_factory):
    class Sub:
        def __init__(self, tag):
            self.tag = tag

        def invoke(self, q):
            return {"success": True, "answer": f"{self.tag}:{q}", "sql": "SELECT 1" if self.tag == "sql" else None}

    from src.agents.router import RouterAgent

    router = RouterAgent(llm=fake_llm_factory([("Classify the request", '{"answer": "sql", "comments": ""}')]))
    agent = DataAgent(router=router, sql_agent=Sub("sql"), etl_agent=Sub("etl"))  # type: ignore[arg-type]
    out = agent.invoke("q")
    assert out == {"success": True, "answer": "sql:q", "route": "sql", "sql": "SELECT 1", "error": None}


def test_production_config_must_be_safe():
    with pytest.raises(ConfigurationError, match="API_KEY"):
        Settings(app_env="production", _env_file=None).validate_for_production()
    Settings(app_env="production", api_key="k", db_readonly_user="ro", _env_file=None).validate_for_production()


def test_empty_api_key_means_open_in_dev(client, monkeypatch):
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "api_key", SecretStr(""))
    assert client.post("/api/v1/query", json={"question": "q"}).status_code == 200
