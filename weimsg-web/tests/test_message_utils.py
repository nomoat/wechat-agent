import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_message_utils_javascript_suite():
    node = shutil.which("node")
    assert node, "node is required to run the front-end message-utils tests"
    result = subprocess.run(
        [node, "--test", str(ROOT / "web" / "tests" / "message-utils.test.cjs")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
