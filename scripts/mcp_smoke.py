"""MCP stdio smoke test script (issue M4, #35).

Starts ``src.mcp_server.server`` as a stdio subprocess with the official MCP Python SDK client, calls ``list_tools``,
and runs ingest -> check_data_sufficiency -> compute_e1rm_and_drift on a real OpenGym export.

Usage: uv run --group rag --group mcp python scripts/mcp_smoke.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "data" / "fixtures" / "opengym" / "fineas_anonymized.csv"
EXERCISE_ID = "Barbell_Bench_Press_-_Medium_Grip"


def _extract_json(result: object) -> dict:
    return json.loads(result.content[0].text)  # type: ignore[attr-defined]


async def run_smoke() -> dict:
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    params = StdioServerParameters(command=sys.executable, args=["-m", "src.mcp_server.server"], env=env, cwd=REPO_ROOT)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = [t.name for t in (await session.list_tools()).tools]

        async def call(name: str, **args: object) -> dict:
            return _extract_json(await session.call_tool(name, args))

        ingest = await call("ingest_workout_log", path=str(FIXTURE), log_id="smoke_log")
        sufficiency = await call("check_data_sufficiency", log_id="smoke_log")
        e1rm = await call("compute_e1rm_and_drift", log_id="smoke_log", exercise_id=EXERCISE_ID)
    return {"tools": tools, "ingest": ingest, "sufficiency": sufficiency, "e1rm": e1rm}


if __name__ == "__main__":
    out = asyncio.run(run_smoke())
    print("Tools:", ", ".join(out["tools"]))
    print("Ingest:", json.dumps(out["ingest"]["counts"]))
    print("Sufficiency:", json.dumps(out["sufficiency"]["reasons"], indent=2))
    print("e1RM:", json.dumps(out["e1rm"]["summary"], indent=2))
