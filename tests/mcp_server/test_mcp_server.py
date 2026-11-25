"""Contract, precondition, isolation, and stdio smoke tests for MCP server (issue M4, #35)."""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path

from src.mcp_server.schemas import TOOL_INPUT_MODELS
from src.mcp_server.server import create_server

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
        assert by_name[tool_name].description, f"Missing description for {tool_name}"


def test_tools_only_no_resources_or_prompts() -> None:
    server = create_server()
    assert asyncio.run(server.list_resources()) == []
    assert asyncio.run(server.list_prompts()) == []


def test_precondition_enforced_before_check_data_sufficiency(tmp_path: Path) -> None:
    csv_path = tmp_path / "log.csv"
    csv_path.write_text(
        "workout_ts,exercise_name_raw,set_type,weight_kg,reps,rpe,failed\n"
        "2026-09-01 10:00:00,Barbell Bench Press,normal,90,5,8.0,false\n"
        "2026-09-08 10:00:00,Barbell Bench Press,normal,92.5,5,8.0,false\n"
        "2026-09-15 10:00:00,Barbell Bench Press,normal,95,5,8.5,false\n"
        "2026-09-22 10:00:00,Barbell Bench Press,normal,97.5,5,8.5,false\n"
        "2026-09-29 10:00:00,Barbell Bench Press,normal,100,5,9.0,false\n"
        "2026-10-06 10:00:00,Barbell Bench Press,normal,100,5,9.0,false\n",
        encoding="utf-8",
    )

    server = create_server()
    ingest = _call_json(server, "ingest_workout_log", {"path": str(csv_path), "log_id": "log_a"})
    assert ingest["log_id"] == "log_a"
    assert "tool_version" in ingest

    # Analysis tools MUST fail with precondition_failed before check_data_sufficiency
    for tool_name, args in (
        ("weekly_sets_per_muscle", {"log_id": "log_a", "weeks": 6}),
        ("compute_e1rm_and_drift", {"log_id": "log_a", "exercise_id": "Barbell_Bench_Press_-_Medium_Grip"}),
        ("uncoupled_load_analyzer", {"log_id": "log_a", "metric": "tonnage"}),
    ):
        err = _call_json(server, tool_name, args)
        assert err["code"] == "precondition_failed", f"{tool_name} bypassed precondition!"

    # Now call check_data_sufficiency for log_a
    suff = _call_json(server, "check_data_sufficiency", {"log_id": "log_a"})
    assert suff["sufficient"] is True
    assert "tool_version" in suff

    # Now analysis tools MUST succeed for log_a
    ws = _call_json(server, "weekly_sets_per_muscle", {"log_id": "log_a", "weeks": 6})
    assert "tool_version" in ws
    assert "code" not in ws

    e1rm = _call_json(
        server,
        "compute_e1rm_and_drift",
        {"log_id": "log_a", "exercise_id": "Barbell_Bench_Press_-_Medium_Grip"},
    )
    assert "tool_version" in e1rm
    assert e1rm["summary"]["sessions_used"] == 6

    load = _call_json(server, "uncoupled_load_analyzer", {"log_id": "log_a", "metric": "tonnage"})
    assert "tool_version" in load
    assert load["summary"]["ratio_label"] == "heuristic"


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
    assert "ingest_workout_log" in out["tools"]
    assert out["sufficiency"]["sufficient"] is True
    assert out["e1rm"]["summary"]["sessions_used"] >= 4
