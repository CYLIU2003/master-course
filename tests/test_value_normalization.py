"""
tests/test_value_normalization.py

normalize_for_python() および loader 出口の ndarray ゼロ混入を検証する。
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# normalize_for_python の単体テスト
# ---------------------------------------------------------------------------

def test_normalize_for_python_passthrough_primitives():
    from src.value_normalization import normalize_for_python
    assert normalize_for_python(1) == 1
    assert normalize_for_python(3.14) == 3.14
    assert normalize_for_python("hello") == "hello"
    assert normalize_for_python(None) is None


def test_normalize_for_python_dict():
    from src.value_normalization import normalize_for_python
    result = normalize_for_python({"a": 1, "b": [2, 3]})
    assert result == {"a": 1, "b": [2, 3]}


def test_normalize_for_python_ndarray():
    np = pytest.importorskip("numpy")
    from src.value_normalization import normalize_for_python
    arr = np.array([1, 2, 3])
    result = normalize_for_python(arr)
    assert isinstance(result, list)
    assert result == [1, 2, 3]


def test_normalize_for_python_ndarray_nested_in_dict():
    np = pytest.importorskip("numpy")
    from src.value_normalization import normalize_for_python
    obj = {"values": np.array([10.0, 20.0]), "label": "test"}
    result = normalize_for_python(obj)
    assert isinstance(result["values"], list)
    assert result["values"] == [10.0, 20.0]
    assert result["label"] == "test"


def test_normalize_for_python_numpy_scalar():
    np = pytest.importorskip("numpy")
    from src.value_normalization import normalize_for_python
    scalar = np.float64(3.14)
    result = normalize_for_python(scalar)
    assert isinstance(result, float)
    assert abs(result - 3.14) < 1e-9


def test_normalize_for_python_numpy_int_scalar():
    np = pytest.importorskip("numpy")
    from src.value_normalization import normalize_for_python
    scalar = np.int32(42)
    result = normalize_for_python(scalar)
    assert isinstance(result, int)
    assert result == 42


def test_normalize_for_python_nested_list_with_ndarray():
    np = pytest.importorskip("numpy")
    from src.value_normalization import normalize_for_python
    obj = [{"x": np.array([1, 2])}, {"x": np.array([3, 4])}]
    result = normalize_for_python(obj)
    assert result == [{"x": [1, 2]}, {"x": [3, 4]}]
    for item in result:
        assert isinstance(item["x"], list)


def test_normalize_for_python_no_ndarray_survives():
    """normalize_for_python 後に numpy.ndarray が残っていないことを保証する再帰チェック"""
    np = pytest.importorskip("numpy")
    from src.value_normalization import normalize_for_python

    obj = {
        "a": np.array([1, 2, 3]),
        "b": {"c": np.float32(1.5)},
        "d": [np.int64(10), "hello", np.array([7, 8])],
    }
    result = normalize_for_python(obj)

    def assert_no_ndarray(o, path=""):
        if isinstance(o, np.ndarray):
            raise AssertionError(f"numpy.ndarray found at {path!r}")
        if isinstance(o, np.generic):
            raise AssertionError(f"numpy.generic found at {path!r}: {type(o)}")
        if isinstance(o, dict):
            for k, v in o.items():
                assert_no_ndarray(v, f"{path}.{k}")
        if isinstance(o, list):
            for i, v in enumerate(o):
                assert_no_ndarray(v, f"{path}[{i}]")

    assert_no_ndarray(result)
