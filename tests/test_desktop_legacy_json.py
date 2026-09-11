from __future__ import annotations

import io
import json
from unittest.mock import patch

import ijson
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bff.routers import desktop
from bff.store import desktop_store
from bff.store.desktop_json import LegacyResultReader


class SmallReads(io.BytesIO):
    def __init__(self, data: bytes, chunk_size: int):
        super().__init__(data)
        self.chunk_size = chunk_size

    def read(self, size: int = -1) -> bytes:
        assert 0 <= size <= 65536, "Source reads must stay bounded"
        return super().read(min(size, self.chunk_size))


@pytest.mark.parametrize("chunk_size", range(1, 35))
def test_legacy_constants_and_escaped_strings_across_read_boundaries(chunk_size):
    text = '日本語 Infinity NaN -Infinity \\" quoted" \\\\ end\\'
    raw = (
        '{"objective_value":Infinity,"cost_breakdown":{"a":-Infinity,"b":NaN},'
        '"feasible":false,"final_accounting_total_cost_jpy":null,"mip_gap":0,'
        '"metadata":{"claim_scope":' + json.dumps(text, ensure_ascii=False) + '},'
        '"ignored":[Infinity,NaN,-Infinity,{"x":"Infinity"}]}'
    ).encode("utf-8")
    expected = json.loads(raw, parse_constant=lambda value: value)
    source = SmallReads(raw, chunk_size)
    with io.BufferedReader(LegacyResultReader(source), buffer_size=13) as reader:
        assert json.load(reader) == expected
    assert not source.closed
    assert source.getvalue() == raw
    projected = desktop_store._stream_projection(SmallReads(raw, chunk_size))
    assert projected == {
        "objective_value": "Infinity",
        "cost_breakdown": {"a": "-Infinity", "b": "NaN"},
        "feasible": False,
        "final_accounting_total_cost_jpy": None,
        "mip_gap": 0,
        "metadata.claim_scope": text,
    }


@pytest.mark.parametrize("token", ["Infinityx", "-NaN", "+Infinity", "1NaN", "nan", "NaN.0"])
def test_malformed_tokens_are_still_rejected(token):
    source = SmallReads(('{"objective_value":' + token + '}').encode(), 1)
    with pytest.raises(ijson.JSONError):
        desktop_store._stream_projection(source)


def test_legacy_nonfinite_projection_is_valid_json_over_http():
    source = io.BytesIO(
        b'{"objective_value":Infinity,"feasible":false,"mip_gap":NaN,'
        b'"solution_validity":{"research_acceptance_status":"REJECTED"},'
        b'"ignored":{"gap":-Infinity}}'
    )
    app = FastAPI()
    app.include_router(desktop.router)
    with patch.object(desktop.scenario_store, "get_desktop_context", return_value=(
        {"meta": {"id": "legacy", "name": "Legacy"}}, {}
    )), patch.object(desktop_store, "collection", return_value={}), patch.object(
        desktop_store, "result_summary", return_value={
            "available": True,
            "source": "optimization_result",
            "values": desktop_store._stream_projection(source),
        }
    ):
        response = TestClient(app).get("/desktop/scenarios/legacy")
    assert response.status_code == 200
    result = response.json()["result"]["values"]
    assert result["objective_value"] == "Infinity"
    assert result["mip_gap"] == "NaN"
    assert result["feasible"] is False
    assert result["solution_validity"]["research_acceptance_status"] == "REJECTED"
