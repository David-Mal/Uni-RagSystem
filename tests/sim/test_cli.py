from pathlib import Path
import subprocess
import sys

import pytest

from scripts.generate_tier2 import main, missing_dependencies

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/generate_tier2.py"


def test_missing_dependencies_leave_output_absent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "output"
    assert main(["--n", "150", "--out", str(output)], repository_root=tmp_path) == 2
    assert not output.exists()
    message = capsys.readouterr().err
    assert all(name in message for name in ("D2", "D3", "P1", "D5", "No output"))
    assert len(missing_dependencies(tmp_path)) == 5


def test_files_alone_cannot_enable_incomplete_generation(tmp_path: Path) -> None:
    # Empty files test only the readiness guard. No fake loader is imported.
    for name in ("docs/opengym-export-format.md", "docs/indicator-spec.md", "data/manifests/partition.yaml",
                 "src/datagen/partition.py", "src/ingest/adapters/opengym.py"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    assert missing_dependencies(tmp_path) == ()
    output = tmp_path / "output"
    assert main(["--out", str(output)], repository_root=tmp_path) == 2
    assert not output.exists()


@pytest.mark.parametrize("n", ("0", "149", "-1", "1.5", "invalid"))
def test_invalid_cli_input(n: str, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["--n", n, "--out", str(tmp_path / "output")], repository_root=tmp_path)
    assert caught.value.code == 2
    assert not (tmp_path / "output").exists()


def test_documented_script_invocation_from_other_directory(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-B", str(SCRIPT), "--n", "150", "--out", str(tmp_path / "output")],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2
    assert "generation is blocked" in result.stderr
    assert not (tmp_path / "output").exists()
