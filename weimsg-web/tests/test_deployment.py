from pathlib import Path


def test_docker_image_installs_ffmpeg():
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
    instructions = dockerfile.read_text()

    assert "apt-get update" in instructions
    assert "apt-get install -y --no-install-recommends ffmpeg" in instructions
    assert "rm -rf /var/lib/apt/lists/*" in instructions
