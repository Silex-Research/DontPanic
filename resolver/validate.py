#!/usr/bin/env python3
"""Universal resolver validator for claude-conventions.

Validates that a project's RESOLVER.md is consistent with its skill files
and shared conventions. Runs the same checks across Jarvis, Styln, and SpinDine.

Usage:
    python3 .claude/shared/resolver/validate.py \
        --resolver .claude/RESOLVER.md \
        --skills-dir .claude/commands/ \
        --conventions-dir .claude/shared/conventions/ \
        [--local-conventions-dir .claude/conventions/]

Exit codes:
    0 = all checks pass
    1 = validation failures found
    2 = usage error (missing args, files not found)
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ── Types ──────────────────────────────────────────────────────────────────────


@dataclass
class Issue:
    check: str
    severity: str  # "error" or "warning"
    message: str
    file: str = ""
    line: int = 0


@dataclass
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    def add(self, check: str, severity: str, message: str, file: str = "", line: int = 0) -> None:
        self.issues.append(Issue(check=check, severity=severity, message=message, file=file, line=line))


# ── Resolver Parsing ──────────────────────────────────────────────────────────


@dataclass
class ResolverRow:
    trigger: str
    skill: str
    path: str
    section: str  # "always-on", "intent", "file-pattern", "error-signal"
    line_number: int
    extra: dict[str, str] = field(default_factory=dict)


def parse_resolver(resolver_path: Path) -> list[ResolverRow]:
    """Parse RESOLVER.md into structured rows."""
    rows: list[ResolverRow] = []
    content = resolver_path.read_text()
    lines = content.split("\n")

    current_section = ""
    section_map = {
        "always-on": "always-on",
        "intent trigger": "intent",
        "intent": "intent",
        "file-pattern trigger": "file-pattern",
        "file-pattern": "file-pattern",
        "error-signal trigger": "error-signal",
        "error-signal": "error-signal",
    }

    for i, line in enumerate(lines, 1):
        # Detect section headers
        header_match = re.match(r"^##\s+(.+)", line)
        if header_match:
            header_text = header_match.group(1).strip().lower()
            for key, section in section_map.items():
                if key in header_text:
                    current_section = section
                    break
            continue

        # Parse table rows (skip header and separator rows)
        if not line.startswith("|") or line.startswith("|---") or line.startswith("| ---"):
            continue

        # Skip table header rows
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if not cells or len(cells) < 2:
            continue

        # Skip separator rows
        if all(re.match(r"^-+$", c) for c in cells if c):
            continue

        # Skip header rows (heuristic: first cell matches a known column name)
        first_cell_lower = cells[0].lower()
        if first_cell_lower in ("trigger keywords", "glob pattern", "stage:errorcode", "skill", "trigger", ""):
            continue

        # Extract skill name and path based on section type
        if current_section == "always-on" and len(cells) >= 2:
            skill = cells[0].strip("`").strip()
            path = cells[1].strip("`").strip()
            rows.append(ResolverRow(
                trigger="*",
                skill=skill,
                path=path,
                section=current_section,
                line_number=i,
            ))
        elif current_section == "intent" and len(cells) >= 3:
            trigger = cells[0].strip('"').strip()
            skill = cells[1].strip("`").strip()
            path = cells[2].strip("`").strip()
            extra = {}
            if len(cells) >= 4:
                extra["precedence"] = cells[3].strip()
            rows.append(ResolverRow(
                trigger=trigger,
                skill=skill,
                path=path,
                section=current_section,
                line_number=i,
                extra=extra,
            ))
        elif current_section == "file-pattern" and len(cells) >= 3:
            trigger = cells[0].strip("`").strip()
            skill = cells[1].strip("`").strip()
            path = cells[2].strip("`").strip()
            extra = {}
            if len(cells) >= 4:
                extra["phase"] = cells[3].strip()
            rows.append(ResolverRow(
                trigger=trigger,
                skill=skill,
                path=path,
                section=current_section,
                line_number=i,
                extra=extra,
            ))
        elif current_section == "error-signal" and len(cells) >= 3:
            trigger = cells[0].strip("`").strip()
            skill = cells[1].strip("`").strip()
            path = cells[2].strip("`").strip()
            rows.append(ResolverRow(
                trigger=trigger,
                skill=skill,
                path=path,
                section=current_section,
                line_number=i,
            ))

    return rows


# ── Skill Parsing ─────────────────────────────────────────────────────────────


@dataclass
class SkillFile:
    name: str
    path: Path
    frontmatter: dict[str, str]
    has_purpose: bool = False
    has_arguments: bool = False
    has_steps: bool = False
    has_output: bool = False
    body: str = ""


def parse_skill(skill_path: Path) -> SkillFile:
    """Parse a skill markdown file, extracting frontmatter and section presence."""
    content = skill_path.read_text()
    name = skill_path.stem

    # Parse YAML frontmatter
    frontmatter: dict[str, str] = {}
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            fm_text = content[3:end].strip()
            for line in fm_text.split("\n"):
                if ":" in line:
                    key, _, val = line.partition(":")
                    frontmatter[key.strip()] = val.strip()

    body_lower = content.lower()

    return SkillFile(
        name=name,
        path=skill_path,
        frontmatter=frontmatter,
        has_purpose="## purpose" in body_lower,
        has_arguments="## arguments" in body_lower,
        has_steps="## steps" in body_lower,
        has_output="## output" in body_lower,
        body=content,
    )


# ── Checks ────────────────────────────────────────────────────────────────────


def check_reachability(
    skills: dict[str, SkillFile],
    resolver_rows: list[ResolverRow],
    report: ValidationReport,
) -> None:
    """Every skill file must have at least one resolver row."""
    referenced_skills = {row.skill for row in resolver_rows}

    for skill_name, skill in skills.items():
        if skill_name not in referenced_skills:
            report.add(
                check="reachability",
                severity="error",
                message=f"Skill '{skill_name}' has no entry in RESOLVER.md — agents cannot discover it",
                file=str(skill.path),
            )


def check_file_existence(
    resolver_rows: list[ResolverRow],
    project_root: Path,
    report: ValidationReport,
    resolver_path: Path,
) -> None:
    """Every resolver row must point to a real file."""
    for row in resolver_rows:
        full_path = project_root / row.path
        if not full_path.exists():
            report.add(
                check="file-existence",
                severity="error",
                message=f"Resolver row points to '{row.path}' which does not exist (skill: {row.skill})",
                file=str(resolver_path),
                line=row.line_number,
            )


def check_mece(
    resolver_rows: list[ResolverRow],
    report: ValidationReport,
    resolver_path: Path,
) -> None:
    """No two intent-trigger rows should share identical keywords without different precedence."""
    intent_rows = [r for r in resolver_rows if r.section == "intent"]

    # Group by trigger
    trigger_groups: dict[str, list[ResolverRow]] = {}
    for row in intent_rows:
        # Normalize trigger for comparison
        key = row.trigger.lower().strip()
        trigger_groups.setdefault(key, []).append(row)

    for trigger, rows in trigger_groups.items():
        if len(rows) <= 1:
            continue

        # Check if they have different precedence values
        precedences = {r.extra.get("precedence", "") for r in rows}
        if len(precedences) == 1:
            skill_names = ", ".join(r.skill for r in rows)
            report.add(
                check="mece",
                severity="error",
                message=f"Duplicate trigger '{trigger}' claimed by [{skill_names}] with same precedence. Add different precedence values or document overlap with <!-- overlap: reason -->",
                file=str(resolver_path),
                line=rows[0].line_number,
            )

    # Check file-pattern rows for same pattern + same phase
    pattern_rows = [r for r in resolver_rows if r.section == "file-pattern"]
    pattern_groups: dict[str, list[ResolverRow]] = {}
    for row in pattern_rows:
        key = f"{row.trigger}|{row.extra.get('phase', '')}"
        pattern_groups.setdefault(key, []).append(row)

    for key, rows in pattern_groups.items():
        if len(rows) <= 1:
            continue
        skill_names = ", ".join(r.skill for r in rows)
        report.add(
            check="mece",
            severity="warning",
            message=f"File pattern '{rows[0].trigger}' (phase: {rows[0].extra.get('phase', 'unset')}) claimed by [{skill_names}]. Intentional overlap should use <!-- overlap: reason --> comment.",
            file=str(resolver_path),
            line=rows[0].line_number,
        )


def check_convention_referencing(
    skills: dict[str, SkillFile],
    conventions_dir: Path,
    local_conventions_dir: Path | None,
    report: ValidationReport,
) -> None:
    """Skills that mention convention topics should reference convention files, not inline rules."""
    # Map convention topics to their files
    topic_patterns: dict[str, list[str]] = {
        "firestore-security": [
            r"enforceAppCheck",
            r"auth\.uid\s*===?\s*userId",
            r"transaction\.get\(\)",
            r"\.limit\(\d+\)",
            r"fire[- ]and[- ]forget",
        ],
        "error-handling": [
            r"HttpsError",
            r"LocalizedError",
            r"try!",
            r"RETRYABLE_",
            r"PERMANENT_",
            r"dead\s*letter",
        ],
        "testing-hierarchy": [
            r"Red/Green",
            r"mock\s+boundar",
            r"behavioral\s+proof",
            r"coverage\s+target",
        ],
        "security": [
            r"App\s*Check",
            r"rate\s*limit",
            r"\.completeFileProtection",
            r"BLOCK_MEDIUM_AND_ABOVE",
            r"PII",
        ],
    }

    for skill_name, skill in skills.items():
        for convention, patterns in topic_patterns.items():
            convention_file = f"conventions/{convention}.md"

            # Check if skill body mentions the topic
            matches = []
            for pattern in patterns:
                if re.search(pattern, skill.body, re.IGNORECASE):
                    matches.append(pattern)

            if not matches:
                continue

            # Check if skill references the convention file
            references_convention = (
                convention in skill.body.lower()
                or convention_file in skill.body
                or f"shared/conventions/{convention}" in skill.body
            )

            if not references_convention:
                report.add(
                    check="convention-referencing",
                    severity="warning",
                    message=f"Skill '{skill_name}' mentions {convention} topics ({matches[0]}) but does not reference {convention_file}. Consider adding: See `.claude/shared/conventions/{convention}.md`",
                    file=str(skill.path),
                )


def check_conformance(
    skills: dict[str, SkillFile],
    report: ValidationReport,
) -> None:
    """Every skill must have required frontmatter and sections per CONFORMANCE.md."""
    required_frontmatter = ["name", "description", "trigger_keywords", "applicable_agents", "phase"]
    required_sections = ["has_purpose", "has_arguments", "has_steps", "has_output"]
    section_names = {"has_purpose": "Purpose", "has_arguments": "Arguments", "has_steps": "Steps", "has_output": "Output"}

    for skill_name, skill in skills.items():
        # Check frontmatter fields
        missing_fm = [f for f in required_frontmatter if f not in skill.frontmatter]
        if missing_fm:
            report.add(
                check="conformance",
                severity="warning",
                message=f"Skill '{skill_name}' missing frontmatter fields: {', '.join(missing_fm)}",
                file=str(skill.path),
            )

        # Check name matches filename
        if "name" in skill.frontmatter and skill.frontmatter["name"] != skill_name:
            report.add(
                check="conformance",
                severity="error",
                message=f"Skill frontmatter name '{skill.frontmatter['name']}' does not match filename '{skill_name}'",
                file=str(skill.path),
            )

        # Check required sections
        missing_sections = [section_names[s] for s in required_sections if not getattr(skill, s)]
        if missing_sections:
            report.add(
                check="conformance",
                severity="warning",
                message=f"Skill '{skill_name}' missing sections: {', '.join(missing_sections)}",
                file=str(skill.path),
            )


# ── Main ──────────────────────────────────────────────────────────────────────


def discover_skills(skills_dir: Path) -> dict[str, SkillFile]:
    """Find and parse skill files in the skills directory.

    Supports two layouts:
    - Flat: skills_dir/{name}.md (Styln/SpinDine commands)
    - Nested: skills_dir/{name}/SKILL.md (Jarvis skills)
    """
    skills: dict[str, SkillFile] = {}
    if not skills_dir.exists():
        return skills

    # Flat layout: *.md files directly in the directory
    for md_file in sorted(skills_dir.glob("*.md")):
        if md_file.name.startswith(".") or md_file.name.upper() == "README.MD":
            continue
        skill = parse_skill(md_file)
        skills[skill.name] = skill

    # Nested layout: {name}/SKILL.md subdirectories
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir() or skill_dir.name.startswith("."):
            continue
        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            skill = parse_skill(skill_md)
            # Use directory name as skill name for nested layout
            skill.name = skill_dir.name
            skills[skill.name] = skill

    return skills


def print_report(report: ValidationReport, resolver_path: Path, skills_count: int, rows_count: int) -> None:
    """Print a formatted validation report."""
    print(f"\n{'=' * 60}")
    print(f"Resolver Validation Report")
    print(f"{'=' * 60}")
    print(f"  Resolver:  {resolver_path}")
    print(f"  Skills:    {skills_count}")
    print(f"  Rows:      {rows_count}")
    print()

    if not report.issues:
        print(f"  \u2713 All {skills_count} skills reachable from resolver")
        print(f"  \u2713 All {rows_count} resolver rows point to existing files")
        print(f"  \u2713 No MECE violations")
        print(f"  \u2713 No convention inlining detected")
        print(f"  \u2713 All skills conform to standard")
        print(f"\n  Result: PASS")
    else:
        # Group by check
        by_check: dict[str, list[Issue]] = {}
        for issue in report.issues:
            by_check.setdefault(issue.check, []).append(issue)

        checks_order = ["reachability", "file-existence", "mece", "convention-referencing", "conformance"]
        all_checks = set(by_check.keys())
        passed_checks = {"reachability", "file-existence", "mece", "convention-referencing", "conformance"} - all_checks

        for check in passed_checks:
            label = check.replace("-", " ").title()
            print(f"  \u2713 {label}: PASS")

        for check in checks_order:
            if check not in by_check:
                continue
            issues = by_check[check]
            errors = [i for i in issues if i.severity == "error"]
            warnings = [i for i in issues if i.severity == "warning"]
            label = check.replace("-", " ").title()

            if errors:
                print(f"  \u2717 {label}: {len(errors)} error(s), {len(warnings)} warning(s)")
            else:
                print(f"  ! {label}: {len(warnings)} warning(s)")

            for issue in issues:
                icon = "\u2717" if issue.severity == "error" else "!"
                loc = ""
                if issue.file and issue.line:
                    loc = f" [{issue.file}:{issue.line}]"
                elif issue.file:
                    loc = f" [{issue.file}]"
                print(f"    {icon} {issue.message}{loc}")

        error_count = len(report.errors)
        warning_count = len(report.warnings)
        result = "FAIL" if error_count > 0 else "WARN"
        print(f"\n  Result: {result} ({error_count} errors, {warning_count} warnings)")

    print(f"{'=' * 60}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate RESOLVER.md against skill files and conventions")
    parser.add_argument("--resolver", required=True, help="Path to RESOLVER.md")
    parser.add_argument("--skills-dir", required=True, nargs="+", help="Path(s) to skills/commands directories")
    parser.add_argument("--conventions-dir", required=True, help="Path to shared conventions directory")
    parser.add_argument("--local-conventions-dir", default=None, help="Path to project-local conventions directory")
    parser.add_argument("--project-root", default=None, help="Project root directory (defaults to resolver parent's parent)")
    args = parser.parse_args()

    resolver_path = Path(args.resolver).resolve()
    skills_dirs = [Path(d).resolve() for d in args.skills_dir]
    conventions_dir = Path(args.conventions_dir).resolve()
    local_conventions_dir = Path(args.local_conventions_dir).resolve() if args.local_conventions_dir else None

    if args.project_root:
        project_root = Path(args.project_root).resolve()
    else:
        # Assume resolver is at .claude/RESOLVER.md, so root is two levels up
        project_root = resolver_path.parent.parent

    # Validate inputs exist
    if not resolver_path.exists():
        print(f"Error: Resolver file not found: {resolver_path}", file=sys.stderr)
        return 2

    for skills_dir in skills_dirs:
        if not skills_dir.exists():
            print(f"Error: Skills directory not found: {skills_dir}", file=sys.stderr)
            return 2

    if not conventions_dir.exists():
        print(f"Error: Conventions directory not found: {conventions_dir}", file=sys.stderr)
        return 2

    # Parse
    resolver_rows = parse_resolver(resolver_path)
    skills: dict[str, SkillFile] = {}
    for skills_dir in skills_dirs:
        skills.update(discover_skills(skills_dir))

    if not skills:
        print(f"Warning: No skill files found in {skills_dir}", file=sys.stderr)

    # Run checks
    report = ValidationReport()

    check_reachability(skills, resolver_rows, report)
    check_file_existence(resolver_rows, project_root, report, resolver_path)
    check_mece(resolver_rows, report, resolver_path)
    check_convention_referencing(skills, conventions_dir, local_conventions_dir, report)
    check_conformance(skills, report)

    # Output
    print_report(report, resolver_path, len(skills), len(resolver_rows))

    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
