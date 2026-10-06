import builtins
import json
import sys

try:
    import resource
except ImportError:
    resource = None

ALLOWED_MODULES = {"pandas", "numpy", "math", "datetime"}
SAFE_BUILTINS = (
    "abs all any bool dict divmod enumerate filter float frozenset int isinstance len list map max min "
    "range reversed round set slice sorted str sum tuple zip print repr bytes complex hash iter next pow "
    "True False None Exception ValueError TypeError KeyError IndexError ZeroDivisionError ArithmeticError"
).split()


def _limits(timeout_s: int, memory_mb: int) -> None:
    if resource is None:
        return
    resource.setrlimit(resource.RLIMIT_CPU, (timeout_s, timeout_s))
    resource.setrlimit(resource.RLIMIT_AS, (memory_mb * 1024 * 1024, memory_mb * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (200 * 1024 * 1024, 200 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def main() -> int:
    workdir, timeout_s, memory_mb = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    max_bytes = memory_mb * 1024 * 1024

    import numpy as np
    import pandas as pd

    code = open(f"{workdir}/code.py", encoding="utf-8").read()
    df = pd.read_parquet(f"{workdir}/in.parquet")
    _limits(timeout_s, memory_mb)

    if resource is None:
        _orig_ones = np.ones
        def _guarded_ones(shape, dtype=None, order="C", **kwargs):
            dt = np.dtype(dtype or float)
            count = shape if isinstance(shape, int) else int(np.prod(shape))
            if count * dt.itemsize > max_bytes:
                raise MemoryError("memory limit exceeded")
            return _orig_ones(shape, dtype=dtype, order=order, **kwargs)
        np.ones = _guarded_ones

    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level or name.split(".")[0] not in ALLOWED_MODULES:
            raise ImportError(f"import of {name!r} is not allowed")
        return real_import(name, globals, locals, fromlist, level)

    safe = {n: getattr(builtins, n) for n in SAFE_BUILTINS if hasattr(builtins, n)}
    safe["__import__"] = guarded_import
    namespace = {"__builtins__": safe, "pd": pd, "np": np, "df": df}

    exec(compile(code, "<llm-generated>", "exec"), namespace)

    for val in namespace.values():
        if isinstance(getattr(val, "nbytes", None), int) and val.nbytes > max_bytes:
            raise MemoryError("memory limit exceeded")

    result = None
    for name in ("result", "output", "data", "df"):
        value = namespace.get(name)
        if isinstance(value, pd.DataFrame):
            result = value
            break
    if result is None:
        print(json.dumps({"status": "no_dataframe"}))
        return 0
    result.to_parquet(f"{workdir}/out.parquet", index=False)
    print(json.dumps({"status": "ok", "rows": len(result), "columns": [str(c) for c in result.columns]}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MemoryError:
        print(json.dumps({"status": "error", "message": "memory limit exceeded"}))
        sys.exit(3)
    except Exception as exc:
        print(json.dumps({"status": "error", "message": f"{type(exc).__name__}: {exc}"[:500]}))
        sys.exit(2)

