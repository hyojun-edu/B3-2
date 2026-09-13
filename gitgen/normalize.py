"""Normalization of model-generated output."""

import re


def clean_text(text: str) -> str:
    return re.sub(r"^```(?:text|markdown)?\s*|\s*```$", "", text.strip(), flags=re.I).strip()


def normalize_commit(text: str, convention: dict) -> str:
    lines = [line.strip() for line in clean_text(text).splitlines() if line.strip()]
    if not lines:
        return "변경 사항 요약"
    title = lines[0].lstrip("- ")[: convention["commit"]["max_title_length"]]
    bullets = [line if line.startswith("-") else f"- {line}" for line in lines[1 : 1 + convention["commit"]["body_bullets"]]]
    return "\n".join([title, *bullets])


def normalize_pr(text: str, convention: dict) -> str:
    text = clean_text(text)
    title_match = re.search(r"(?im)^title:\s*(.+)$", text)
    title = (title_match.group(1).strip() if title_match else "변경 사항 반영")[:80]
    sections = {}
    for name in convention["pr"]["sections"]:
        match = re.search(rf"(?ms)^##\s*{re.escape(name)}\s*\n(.*?)(?=^##\s|\Z)", text)
        content = match.group(1).strip() if match else "- 변경 사항을 확인합니다."
        bullets = [line.strip() for line in content.splitlines() if line.strip().startswith("-")]
        sections[name] = "\n".join(bullets or ["- 변경 사항을 확인합니다."])
    return f"Title: {title}\n\n" + "\n\n".join(f"## {name}\n{sections[name]}" for name in sections)


def normalize_result(command: str, text: str, convention: dict) -> str:
    return normalize_commit(text, convention) if command == "commit" else normalize_pr(text, convention)
