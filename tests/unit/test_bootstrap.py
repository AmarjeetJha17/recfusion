import tomllib
from pathlib import Path

import recfusion_core


def test_project_metadata_declares_python_313() -> None:
    pyproject_path = Path(__file__).parents[2] / "pyproject.toml"
    with pyproject_path.open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)

    assert pyproject["project"]["name"] == "recfusion"
    assert pyproject["project"]["requires-python"] == ">=3.13,<3.14"


def test_core_package_is_importable() -> None:
    assert recfusion_core.__doc__ == "Core contracts and domain types for RecFusion."
