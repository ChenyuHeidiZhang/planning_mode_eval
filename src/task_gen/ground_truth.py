"""Extract ground truth (files_modified, files_created, libraries_added, key_additions) from a merge diff."""
import re
from dataclasses import dataclass, field


@dataclass
class GroundTruth:
    files_modified: list[str] = field(default_factory=list)
    files_created: list[str] = field(default_factory=list)
    key_additions: list[str] = field(default_factory=list)
    libraries_added: list[str] = field(default_factory=list)


def _parse_diff_files(diff: str) -> tuple[list[str], list[str]]:
    """Parse git diff for file paths. Returns (modified, created)."""
    modified = []
    created = []
    lines = diff.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(.+?) b/(.+?)(?:\s|$)", line)
            if m:
                a_path, b_path = m.group(1), m.group(2)
                is_new = a_path == "/dev/null"
                i += 1
                while i < len(lines) and not lines[i].startswith("diff --git "):
                    if lines[i].startswith("new file mode ") or lines[i].startswith("new file"):
                        is_new = True
                    i += 1
                if is_new:
                    created.append(b_path)
                else:
                    modified.append(b_path)
            else:
                i += 1
        else:
            i += 1
    created = list(dict.fromkeys(created))
    modified = [p for p in dict.fromkeys(modified) if p not in created]
    return modified, created


def _parse_libraries_added(diff: str) -> list[str]:
    """Detect added dependencies in package.json or requirements.txt from diff."""
    added = []
    # package.json: look for "+  \"name\": ..." in dependencies
    in_deps = False
    for line in diff.splitlines():
        if "package.json" in line and line.startswith("+++"):
            in_deps = True
        if not line.startswith("+") or line == "+++ " or line.startswith("+++ "):
            if line.startswith("+"):
                stripped = line[1:].strip()
                # "axios-retry": "^1.2.3" or 'axios-retry':
                m = re.search(r'["\']([^"\']+)["\']\s*:', stripped)
                if m and not stripped.startswith("//"):
                    dep = m.group(1)
                    if dep not in ("name", "version", "description", "scripts", "main", "dependencies", "devDependencies"):
                        added.append(dep)
    # requirements.txt: + package-name
    for line in diff.splitlines():
        if line.startswith("+") and "requirements" in diff and not line.startswith("+++"):
            stripped = line[1:].strip().split("#")[0].strip()
            if stripped and not stripped.startswith("-") and "==" in stripped or re.match(r"^[a-zA-Z0-9_-]+$", stripped):
                added.append(stripped.split("==")[0].split("[")[0])
    return list(dict.fromkeys(added))


def _heuristic_key_additions(message: str, diff: str) -> list[str]:
    """Simple heuristic: extract phrases from commit message and diff hints."""
    key_additions = []
    # From message: first line often summarizes
    first_line = message.split("\n")[0].strip()
    if first_line and len(first_line) < 200:
        key_additions.append(first_line)
    # From diff: common patterns
    if "retry" in diff.lower() or "retry" in message.lower():
        key_additions.append("retry logic")
    if "constant" in diff.lower() or "CONST" in diff or "MAX_" in diff:
        key_additions.append("constant")
    if "test" in diff.lower() and ("+def " in diff or "+it(" in diff or "+test" in diff):
        key_additions.append("tests")
    return key_additions[:5]  # cap


def extract_ground_truth(diff: str, commit_message: str) -> GroundTruth:
    """
    Parse diff and commit_message to produce GroundTruth.
    key_additions uses heuristic; can be overridden later with LLM summary.
    """
    files_modified, files_created = _parse_diff_files(diff)
    libraries_added = _parse_libraries_added(diff)
    key_additions = _heuristic_key_additions(commit_message, diff)
    return GroundTruth(
        files_modified=files_modified,
        files_created=files_created,
        key_additions=key_additions,
        libraries_added=libraries_added,
    )
