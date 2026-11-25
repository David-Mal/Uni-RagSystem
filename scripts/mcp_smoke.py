"""MCP stdio smoke test script (issue M4, #35).

Starts ``src.mcp_server.server`` as a stdio subprocess with the official MCP Python SDK client,
calls ``list_tools``, and runs ingest -> check_data_sufficiency -> compute_e1rm_and_drift
on an OpenGym fixture (falling back to a self-contained temp fixture if none is present yet).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = REPO_ROOT / "data" / "fixtures" / "opengym" / "fineas_anonymized.csv"


def _ensure_fixture() -> tuple[Path, bool]:
    if DEFAULT_FIXTURE.exists():
        return DEFAULT_FIXTURE, False
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as tmp:
        tmp.write("workout_ts,exercise_name_raw,set_type,weight_kg,reps,rpe,failed\n")
        rows = [
            ("2026-09-01 10:00:00", "Barbell Bench Press", "normal", "90", "5", "8.0", "false"),
            ("2026-09-08 10:00:00", "Barbell Bench Press", "normal", "92.5", "5", "8.0", "false"),
            ("2026-09-15 10:00:00", "Barbell Bench Press", "normal", "95", "5", "8.5", "false"),
            ("2026-09-22 10:00:00", "Barbell Bench Press", "normal", "97.5", "5", "8.5", "false"),
            ("2026-09-29 10:00:00", "Barbell Bench Press", "normal", "100", "5", "9.0", "false"),
            ("2026-10-06 10:00:00", "Barbell Bench Press", "normal", "100", "5", "9.0", "false"),
        ]
        for r in rows:
            tmp.write(",".join(r) + "\n")
        return Path(tmp.name), True


def _extract_json(result: object) -> dict:
    content = getattr(result, "content", [])
    if content:
        text = getattr(content[0], "text", "{}")
        return json.loads(text)
    return {}


async def run_smoke() -> dict:
    fixture_path, is_temp = _ensure_fixture()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.mcp_server.server"],
        env=env,
    )
    try:
        async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
                await session.initialize()

                tools_resp = await session.list_tools()
                tool_names = [t.name for t in tools_resp.tools]
                print("Tools registered:", tool_names)

                ingest_res = _extract_json(
                    await session.call_tool(
                        "ingest_workout_log",
                        {"path": str(fixture_path), "log_id": "smoke_log"},
                    )
                )
                print("Ingest result:", json.dumps(ingest_res, indent=2))

                suff_res = _extract_json(
                    await session.call_tool(
                        "check_data_sufficiency",
                        {"log_id": "smoke_log"},
                    )
                )
                print("Sufficiency result:", json.dumps(suff_res, indent=2))

                ex_id = (
                    suff_res.get("eligible_exercise_ids", ["Barbell_Bench_Press_-_Medium_Grip"])[0]
                    if suff_res.get("eligible_exercise_ids")
                    else "Barbell_Bench_Press_-_Medium_Grip"
                )
                e1rm_res = _extract_json(
                    await session.call_tool(
                        "compute_e1rm_and_drift",
                        {"log_id": "smoke_log", "exercise_id": ex_id},
                    )
                )
                print("e1RM result:", json.dumps(e1rm_res, indent=2))
                return {
                    "tools": tool_names,
                    "ingest": ingest_res,
                    "sufficiency": suff_res,
                    "e1rm": e1rm_res,
                }
    finally:
        if is_temp and fixture_path.exists():
            fixture_path.unlink()


if __name__ == "__main__":
    asyncio.run(run_smoke())
