import pandas as pd
import pytest

from src.core.exceptions import SecurityError, ToolExecutionError
from src.security.code_validator import CodeValidator
from src.security.sandbox import Sandbox

cv = CodeValidator()

ESCAPES = [
    "o = df.__class__.__init__.__globals__['__builtins__']['__import__']('os')",
    "x = ().__class__.__bases__[0].__subclasses__()",
    "f = getattr(df, 'to_' + 'csv')",
    "t = type(df)",
    "import os",
    "import subprocess",
    "from os import path",
    "open('/etc/passwd')",
    "eval('1+1')",
    "exec('x=1')",
    "df.eval('a+1')",
    "df.query('a > 1')",
    "pd.read_csv('/etc/passwd')",
    "pd.read_pickle('x.pkl')",
    "df.to_pickle('x.pkl')",
    "df.to_csv('/tmp/x.csv')",
    "np.load('x.npy', allow_pickle=True)",
    "x = df.style",
    "class A: pass",
    "try:\n    x = 1\nexcept Exception:\n    pass",
    "x = '__class__'",
    "while True:\n    global y",
]


@pytest.mark.parametrize("code", ESCAPES)
def test_validator_blocks_escape_attempts(code):
    assert not cv.validate(code), code


@pytest.mark.parametrize(
    "code",
    [
        "result = df.groupby('a')['b'].sum().reset_index()",
        "import pandas as pd\nimport numpy as np\nresult = df.assign(c=np.log1p(df['b']))",
        "df['d'] = df['b'].apply(lambda v: v * 2)\nresult = df",
        "result = df[df['a'] > 1].sort_values('b', ascending=False)",
    ],
)
def test_validator_allows_normal_pandas(code):
    ok, reason = cv.check(code)
    assert ok, reason


@pytest.fixture
def frame():
    return pd.DataFrame({"a": [1, 1, 2, 3], "b": [10, 20, 30, 40]})


def test_sandbox_runs_valid_code(frame):
    out = Sandbox().run_dataframe("result = df.groupby('a', as_index=False)['b'].sum()", frame)
    assert out is not None and out.to_dict("records") == [{"a": 1, "b": 30}, {"a": 2, "b": 30}, {"a": 3, "b": 40}]


def test_sandbox_returns_none_without_dataframe(frame):
    assert Sandbox().run_dataframe("df = 5", frame) is None


def test_sandbox_rejects_before_spawning(frame):
    with pytest.raises(SecurityError):
        Sandbox().run_dataframe("import os", frame)


def test_sandbox_reports_runtime_errors(frame):
    with pytest.raises(ToolExecutionError, match="KeyError"):
        Sandbox().run_dataframe("result = df[['nope']]", frame)


def test_sandbox_enforces_cpu_limit(frame):
    with pytest.raises(ToolExecutionError):
        Sandbox(timeout_s=2).run_dataframe("while True:\n    pass", frame)


def test_sandbox_enforces_memory_limit(frame):
    with pytest.raises(ToolExecutionError):
        Sandbox(memory_mb=600).run_dataframe("x = np.ones(10**9)\nresult = df", frame)


def test_sandbox_allows_allowlisted_imports(frame):
    out = Sandbox().run_dataframe("import math\nresult = df.assign(m=math.pi)", frame)
    assert out is not None and "m" in out.columns
