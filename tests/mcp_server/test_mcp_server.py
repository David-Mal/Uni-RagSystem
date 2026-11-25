"""Contract, precondition, isolation, and stdio smoke tests for MCP server (issue M4, #35)."""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from src.mcp_server.schemas import TOOL_INPUT_MODELS, TOOL_OUTPUT_MODELS, ToolErrorOutput  # noqa: E402
from src.mcp_server.server import create_server, load_retriever  # noqa: E402
from src.rag.build import build_index  # noqa: E402
from src.rag.store import HashEmbedder  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


def _call_json(server, name: str, args: dict) -> dict:
    res = asyncio.run(server.call_tool(name, args))
    # MCPServer.call_tool returns CallToolResult with content[0].text
    text = res.content[0].text
    return json.loads(text)


def test_list_tools_matches_pydantic_input_models() -> None:
    server = create_server()
    tools = asyncio.run(server.list_tools())
    by_name = {t.name: t for t in tools}

    assert set(by_name.keys()) == set(TOOL_INPUT_MODELS.keys())
    # Gate and verifier must NOT be registered as MCP tools
    assert "safety_gate" not in by_name
    assert "output_verifier" not in by_name

    for tool_name, model_cls in TOOL_INPUT_MODELS.items():
        mcp_schema = getattr(by_name[tool_name], "input_schema", None) or by_name[tool_name].inputSchema
        pydantic_schema = model_cls.model_json_schema()

        assert set(mcp_schema.get("properties", {}).keys()) == set(
            pydantic_schema.get("properties", {}).keys()
        ), f"Schema property mismatch for {tool_name}"
        assert set(mcp_schema.get("required", [])) == set(
            pydantic_schema.get("required", [])
        ), f"Required fields mismatch for {tool_name}"
        for field, prop in pydantic_schema.get("properties", {}).items():
            same = {k: v for k, v in prop.items() if k not in ("title", "description")}
            got = mcp_schema["properties"][field]
            assert {k: v for k, v in got.items() if k not in ("title", "description")} == same, (tool_name, field)
        assert by_name[tool_name].description, f"Missing description for {tool_name}"


def test_tools_only_no_resources_or_prompts() -> None:
    server = create_server()
    assert asyncio.run(server.list_resources()) == []
    assert asyncio.run(server.list_prompts()) == []


BENCH = "Barbell_Bench_Press_-_Medium_Grip"
FIXTURE = REPO_ROOT / "data" / "fixtures" / "opengym" / "fineas_anonymized.csv"


def _ingested(log_id: str = "log_a"):
    server = create_server()
    out = _call_json(server, "ingest_workout_log", {"path": str(FIXTURE), "log_id": log_id})
    assert out["counts"]["sets_added"] == 276
    return server, out


ANALYSIS = (
    ("weekly_sets_per_muscle", {"weeks": 6}),
    ("compute_e1rm_and_drift", {"exercise_id": BENCH}),
    ("uncoupled_load_analyzer", {"metric": "tonnage"}),
)


def test_precondition_enforced_before_check_data_sufficiency() -> None:
    server, ingest = _ingested()
    assert ingest["unmatched_names"] == ["Cable Leaning Lateral Raise"]
    for tool_name, args in ANALYSIS:
        err = _call_json(server, tool_name, {"log_id": "log_a", **args})
        assert err["code"] == "precondition_failed", f"{tool_name} bypassed precondition!"
        ToolErrorOutput.model_validate(err)

    suff = _call_json(server, "check_data_sufficiency", {"log_id": "log_a"})
    assert suff["allowed_analyses"] == ["weekly_volume", "e1rm_trend"]
    for tool_name, args in ANALYSIS:
        out = _call_json(server, tool_name, {"log_id": "log_a", **args})
        assert out.get("code") != "precondition_failed"
        assert "tool_version" in out
    # A check of one log does not open another one
    assert _call_json(server, "weekly_sets_per_muscle", {"log_id": "log_b"})["code"] == "precondition_failed"


def test_outputs_match_the_output_models() -> None:
    server, ingest = _ingested()
    outputs = {
        "ingest_workout_log": ingest,
        "match_exercise_rag": _call_json(server, "match_exercise_rag", {"name": "RDL"}),
        "check_data_sufficiency": _call_json(server, "check_data_sufficiency", {"log_id": "log_a"}),
        "weekly_sets_per_muscle": _call_json(server, "weekly_sets_per_muscle", {"log_id": "log_a"}),
        "compute_e1rm_and_drift": _call_json(
            server, "compute_e1rm_and_drift", {"log_id": "log_a", "exercise_id": BENCH}
        ),
        "retrieve_knowledge": _call_json(
            server, "retrieve_knowledge", {"query": "volume", "allowed_exercise_ids": [], "allowed_hypotheses": []}
        ),
    }
    for name, out in outputs.items():
        assert out["tool_version"].startswith(name)
        TOOL_OUTPUT_MODELS[name].model_validate(out)
    load = _call_json(server, "uncoupled_load_analyzer", {"log_id": "log_a"})
    assert load["code"] == "insufficient_history" and load["tool_version"].startswith("uncoupled_load_analyzer")
    assert set(TOOL_OUTPUT_MODELS) == set(TOOL_INPUT_MODELS)


def test_value_ids_are_unique_across_the_tools_of_a_run() -> None:
    server, _ = _ingested()
    outs = [
        _call_json(server, "check_data_sufficiency", {"log_id": "log_a"}),
        _call_json(server, "weekly_sets_per_muscle", {"log_id": "log_a"}),
        _call_json(server, "compute_e1rm_and_drift", {"log_id": "log_a", "exercise_id": BENCH}),
        _call_json(server, "compute_e1rm_and_drift", {"log_id": "log_a", "exercise_id": BENCH}),
    ]
    ids = [v["value_id"] for out in outs for v in out["values"]]
    assert len(ids) == len(set(ids)) > 20


def test_exclusions_of_the_check_hold_for_every_later_call() -> None:
    server, _ = _ingested()
    _call_json(server, "check_data_sufficiency", {"log_id": "log_a", "allowed_exercise_ids": ["Pullups"]})
    args = {"log_id": "log_a", "exercise_id": BENCH}
    assert _call_json(server, "compute_e1rm_and_drift", args)["code"] == "exercise_not_allowed"
    # Neither asking for it nor checking again widens the set
    args["allowed_exercise_ids"] = [BENCH]
    assert _call_json(server, "compute_e1rm_and_drift", args)["code"] == "exercise_not_allowed"
    _call_json(server, "check_data_sufficiency", {"log_id": "log_a"})
    assert _call_json(server, "compute_e1rm_and_drift", args)["code"] == "exercise_not_allowed"
    weekly = _call_json(server, "weekly_sets_per_muscle", {"log_id": "log_a"})
    assert weekly["table"] == [] and weekly["excluded_counts"]["not_allowed"] > 0


def test_bad_inputs_are_structured_errors(tmp_path: Path) -> None:
    server, _ = _ingested()
    bad = tmp_path / "x.csv"
    bad.write_text("a,b\n1,2\n", encoding="utf-8")
    assert _call_json(server, "ingest_workout_log", {"path": str(bad)})["message"] == "unknown format"
    assert _call_json(server, "ingest_workout_log", {"path": str(tmp_path / "no.csv")})["code"] == "ingest_error"
    assert _call_json(server, "check_data_sufficiency", {"log_id": "nope"})["code"] == "unknown_log"
    _call_json(server, "check_data_sufficiency", {"log_id": "log_a"})
    assert _call_json(server, "weekly_sets_per_muscle", {"log_id": "log_a", "weeks": 0})["code"] == "invalid_weeks"


def test_index_is_optional_and_loaded_when_built(tmp_path: Path) -> None:
    assert load_retriever(tmp_path) is None
    build_index(
        index_dir=tmp_path,
        embedder=HashEmbedder(),
        synthesis_dir=REPO_ROOT / "tests" / "data" / "knowledge",
        include_exercises=False,
    )
    server = create_server(knowledge_retriever=load_retriever(tmp_path))
    out = _call_json(
        server,
        "retrieve_knowledge",
        {"query": "weekly effective sets", "allowed_exercise_ids": [BENCH],
         "allowed_hypotheses": ["insufficient_weekly_volume"]},
    )  # fmt: skip
    assert [c["chunk_id"] for c in out["chunks"]] == ["syn_vol#c01"]


def test_no_mcp_import_outside_server_module() -> None:
    src_dir = REPO_ROOT / "src"
    allowed = (src_dir / "mcp_server" / "server.py").resolve()
    for py_file in src_dir.rglob("*.py"):
        if py_file.resolve() == allowed:
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("mcp"), f"Forbidden mcp import in {py_file}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("mcp"), f"Forbidden mcp import in {py_file}"


def test_stdio_smoke_script_end_to_end() -> None:
    from scripts.mcp_smoke import run_smoke

    out = asyncio.run(run_smoke())
    assert set(out["tools"]) == set(TOOL_INPUT_MODELS)
    assert out["sufficiency"]["sufficient"] is True
    assert out["e1rm"]["sessions_used"] >= 4
