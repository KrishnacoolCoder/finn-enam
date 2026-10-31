"""Add Hugging Face Docker Space frontmatter without replacing FINN's README."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADER = """---
title: FINN Investment Intelligence
emoji: 📈
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
short_description: Source-linked Indian equities intelligence prototype
---

"""


def prepare_readme(path: Path) -> bool:
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig")
    if text.startswith("---\n"):
        head = text.split("---", 2)
        if len(head) > 2 and "sdk: docker" in head[1] and "app_port: 7860" in head[1]:
            return False
        raise ValueError("README already has frontmatter; review it manually before editing")
    path.write_text(HEADER + text, encoding="utf-8")
    return True


if __name__ == "__main__":
    changed = prepare_readme(ROOT / "README.md")
    print("Added Hugging Face Docker metadata to README.md" if changed
          else "README.md already has correct Hugging Face Docker metadata")
