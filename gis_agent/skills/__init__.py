from pathlib import Path

import yaml


def skill_index() -> list[dict[str, str]]:
    skills = []
    for path in sorted(Path(__file__).parent.glob("*/SKILL.md")):
        frontmatter = path.read_text(encoding="utf-8").split("---", 2)
        if len(frontmatter) != 3 or frontmatter[0].strip():
            raise ValueError(f"Skill缺少YAML头：{path}")
        metadata = yaml.safe_load(frontmatter[1])
        if not isinstance(metadata, dict) or any(not isinstance(metadata.get(key), str) or not metadata[key].strip()
                                                 for key in ("name", "description")):
            raise ValueError(f"Skill需要name和description：{path}")
        skills.append({"name": metadata["name"], "description": metadata["description"], "path": path.resolve().as_posix()})
    return skills
