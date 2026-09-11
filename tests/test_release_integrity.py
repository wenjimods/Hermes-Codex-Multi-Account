from pathlib import Path
import re
import tomllib


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_release_version_is_consistent() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project_version = project["project"]["version"]

    manifest = (REPO_ROOT / "src/backend/codex-quota-status/plugin.yaml").read_text(encoding="utf-8")
    match = re.search(r"^version:\s*([^\s]+)\s*$", manifest, flags=re.MULTILINE)
    assert match is not None
    assert match.group(1) == project_version

    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{project_version}]" in changelog
