import json

import pandas as pd
import pytest

from src.agents.etl_analyst import ETLAnalystAgent, clean_code, parse_tool_call
from src.tools.etl import ETLTools


@pytest.mark.parametrize(
    "text",
    [
        'extract_load_tool: url: "https://pokeapi.co/api/v2/pokemon" output_folder: "extract" format: "csv"',
        'extract_load_tool(url="https://pokeapi.co/api/v2/pokemon", output_folder="extract", format="csv")',  # the prompt's own old syntax
        "{\"tool\": \"extract\", \"url\": \"https://pokeapi.co/api/v2/pokemon\", \"format\": \"csv\"}",
    ],
)
def test_parse_tool_call_accepts_the_syntaxes_models_produce(text):
    plan = parse_tool_call(text)
    assert plan and plan.tool == "extract" and plan.url == "https://pokeapi.co/api/v2/pokemon" and plan.format == "csv"


def test_parse_tool_call_transform_with_extract_in_path():
    # Regression: "extract/" in the file path used to hijack routing to the extract tool.
    plan = parse_tool_call('transform_load_tool(input_file_path="data/extract/extracted_data.csv", output_format="csv")')
    assert plan and plan.tool == "transform" and plan.input_file_path == "data/extract/extracted_data.csv"


def test_parse_tool_call_returns_none_for_prose():
    assert parse_tool_call("I think you should relax.") is None


def test_clean_code_strips_fences():
    assert clean_code("```python\nresult = df\n```") == "result = df"


class SpyTools(ETLTools):
    def __init__(self, base):
        super().__init__(base)
        self.extract_calls = 0

    def extract_load(self, url, output_folder, format):  # noqa: A002
        self.extract_calls += 1
        return {"status": "success", "rows": 2, "filename": "extract/extracted_data.csv", "message": "ok"}


def test_extract_runs_exactly_once_and_succeeds(tmp_path, fake_llm_factory):
    plan = json.dumps({"tool": "extract", "url": "https://pokeapi.co/x", "output_folder": "extract", "format": "csv"})
    tools = SpyTools(str(tmp_path))
    llm = fake_llm_factory([("You plan data tasks", plan), ("ETL operation just ran", "Saved 2 rows.")])
    out = ETLAnalystAgent(tools=tools, llm=llm).invoke("extract data from the api")
    assert out["success"] and out["answer"] == "Saved 2 rows."
    assert tools.extract_calls == 1  # the old graph re-ran the tool every loop and then crashed on ToolMessage


def test_summary_failure_falls_back_to_tool_message(tmp_path, fake_llm_factory):
    plan = json.dumps({"tool": "extract", "url": "https://pokeapi.co/x"})
    llm = fake_llm_factory([("You plan data tasks", plan)])  # no rule for the summary prompt -> LLM raises
    out = ETLAnalystAgent(tools=SpyTools(str(tmp_path)), llm=llm).invoke("extract")
    assert out["success"] and "ETL completed" in out["answer"]


def test_incomplete_plan_is_an_error(tmp_path, fake_llm_factory):
    llm = fake_llm_factory([("You plan data tasks", json.dumps({"tool": "extract"}))])
    out = ETLAnalystAgent(tools=SpyTools(str(tmp_path)), llm=llm).invoke("extract")
    assert not out["success"] and "URL" in out["answer"]


def test_ssrf_and_traversal_surface_as_clean_errors(tmp_path, fake_llm_factory):
    plan = json.dumps({"tool": "extract", "url": "http://169.254.169.254/latest/meta-data", "output_folder": "../../x"})
    llm = fake_llm_factory([("You plan data tasks", plan)])
    out = ETLAnalystAgent(tools=ETLTools(str(tmp_path)), llm=llm).invoke("extract")
    assert not out["success"] and "not in ETL_ALLOWED_HOSTS" in out["answer"]


def test_transform_flow_runs_generated_code_in_sandbox(tmp_path, fake_llm_factory):
    tools = ETLTools(str(tmp_path))
    pd.DataFrame({"a": [1, 2, 3]}).to_csv(tools.base_dir / "in.csv", index=False)
    llm = fake_llm_factory(
        [
            ("You plan data tasks", json.dumps({"tool": "transform", "input_file_path": "in.csv", "output_format": "csv"})),
            ("Write pandas code", "```python\nresult = df[df['a'] > 1]\n```"),
            ("ETL operation just ran", "Filtered."),
        ]
    )
    out = ETLAnalystAgent(tools=tools, llm=llm).invoke("transform in.csv keep a>1")
    assert out["success"], out
    assert pd.read_csv(tools.base_dir / "transform" / "transformed_data.csv")["a"].tolist() == [2, 3]


def test_transform_with_malicious_generated_code_is_blocked(tmp_path, fake_llm_factory):
    tools = ETLTools(str(tmp_path))
    pd.DataFrame({"a": [1]}).to_csv(tools.base_dir / "in.csv", index=False)
    llm = fake_llm_factory(
        [
            ("You plan data tasks", json.dumps({"tool": "transform", "input_file_path": "in.csv"})),
            ("Write pandas code", "o = df.__class__.__init__.__globals__['__builtins__']\nresult = df"),
        ]
    )
    out = ETLAnalystAgent(tools=tools, llm=llm).invoke("transform")
    assert not out["success"] and "rejected" in out["answer"]
