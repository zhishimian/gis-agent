from pathlib import Path

from gis_agent.tools.files import read_file, write_file


def test_write_refuses_overwrite(tmp_path: Path) -> None:
    path = str(tmp_path / "说明.txt")

    assert write_file(path, "道路数据")["ok"]
    assert not write_file(path, "被覆盖的内容")["ok"]
    assert read_file(path)["content"] == "道路数据"