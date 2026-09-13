"""Prompt construction for commit messages and pull requests."""


def commit_prompt(status: str, diff: str, convention: dict) -> str:
    rules = convention["commit"]
    prefixes = ", ".join(rules["prefixes"])
    scope = "Use a scope in parentheses when useful." if rules["scope"] else "Do not use a scope."
    return f"""Create a commit message from this Git change. Output only the message: a single title line (maximum {rules['max_title_length']} characters), optionally followed by a blank line and up to {rules['body_bullets']} bullet lines. Write in {convention['language']}. Use one of these exact prefixes with the configured capitalization: {prefixes}. {scope} Keep the message concise and factual.\n\nGit status:\n{status}\n\nGit diff:\n{diff}"""


def pr_prompt(status: str, diff: str, convention: dict) -> str:
    rules = convention["pr"]
    commit_rules = convention["commit"]
    sections = rules["sections"]
    section_format = "\n\n".join(f"## {name}\n- ..." for name in sections)
    if rules["title_prefix"]:
        prefixes = ", ".join(commit_rules["prefixes"])
        prefix_rule = f"Use one of these exact title prefixes with the configured capitalization: {prefixes}."
    else:
        prefix_rule = "Do not force a prefix in the title."
    return f"""Create a pull request draft from this Git change. Use a {rules['tone']} tone. Write the title and all section content in {convention['language']}. Output exactly this Markdown structure, with at least one bullet under every section:\nTitle: <one-line title, maximum 80 characters>\n\n{section_format}\n{prefix_rule} Do not add unconfigured sections. Use the actual change and sensible test commands.\n\nGit status:\n{status}\n\nGit diff:\n{diff}"""


def build_prompt(command: str, status: str, diff: str, convention: dict) -> str:
    return commit_prompt(status, diff, convention) if command == "commit" else pr_prompt(status, diff, convention)
