#!/usr/bin/env python3
"""Validate a plan directory against v1.0 schemas.

Usage: validate_plan.py <plan-id>
Run from project root (expects docs/plans/<plan-id>/ and docs/plans/.schemas/).

Pre-Phase-0 version: reads local copies of schemas in docs/plans/.schemas/.
After Phase 0 promotion, schemas live in agent-conventions/schemas/v1.0/.
"""
import json
import re
import sys
from pathlib import Path

try:
    import jsonschema
    import yaml
except ImportError:
    sys.exit("Install deps: pip3 install jsonschema pyyaml")


def main() -> int:
    if len(sys.argv) != 2:
        sys.exit(f"Usage: {sys.argv[0]} <plan-id>")
    plan_id = sys.argv[1]

    cwd = Path.cwd()
    plans_root = cwd / "docs" / "plans"
    plan_dir = plans_root / plan_id
    schemas_dir = plans_root / ".schemas"

    if not plan_dir.is_dir():
        sys.exit(f"Not found: {plan_dir}")
    if not schemas_dir.is_dir():
        sys.exit(f"Not found: {schemas_dir}. Run bootstrap_project.sh first.")

    errors = 0

    # features.json
    try:
        schema = json.loads((schemas_dir / "features.schema.json").read_text())
        instance = json.loads((plan_dir / "features.json").read_text())
        jsonschema.validate(instance=instance, schema=schema)
        print("features.json ✓")
    except jsonschema.ValidationError as e:
        print(f"features.json ✗ path={list(e.absolute_path)} msg={e.message}")
        errors += 1
    except FileNotFoundError as e:
        print(f"features.json ✗ {e}")
        errors += 1

    # plan.md frontmatter
    try:
        md = (plan_dir / "plan.md").read_text()
        m = re.match(r"^---\n(.*?)\n---", md, re.DOTALL)
        if not m:
            print("plan.md ✗ no frontmatter found")
            errors += 1
        else:
            frontmatter = yaml.safe_load(m.group(1))
            schema = json.loads((schemas_dir / "plan.schema.json").read_text())
            jsonschema.validate(instance=frontmatter, schema=schema)
            print("plan.md frontmatter ✓")
    except jsonschema.ValidationError as e:
        print(f"plan.md ✗ path={list(e.absolute_path)} msg={e.message}")
        errors += 1
    except FileNotFoundError as e:
        print(f"plan.md ✗ {e}")
        errors += 1

    # decisions.jsonl
    decisions_path = plan_dir / "decisions.jsonl"
    if decisions_path.exists():
        try:
            for i, line in enumerate(decisions_path.read_text().splitlines(), 1):
                line = line.strip()
                if line:
                    json.loads(line)
            print("decisions.jsonl ✓")
        except json.JSONDecodeError as e:
            print(f"decisions.jsonl ✗ line {i}: {e}")
            errors += 1

    # audit JSONs
    audit_dir = plan_dir / "audit"
    if audit_dir.is_dir():
        try:
            schema = json.loads((schemas_dir / "audit.schema.json").read_text())
        except FileNotFoundError:
            schema = None
        for audit_file in sorted(audit_dir.glob("*.json")):
            if "fixture" in audit_file.name:
                continue
            try:
                instance = json.loads(audit_file.read_text())
                if schema:
                    jsonschema.validate(instance=instance, schema=schema)
                status = instance.get("audit_status", "?")
                n = len(instance.get("findings", []))
                print(f"{audit_file.name} ✓ status={status} findings={n}")
            except jsonschema.ValidationError as e:
                print(f"{audit_file.name} ✗ {e.message[:120]}")
                errors += 1
            except json.JSONDecodeError as e:
                print(f"{audit_file.name} ✗ malformed JSON: {e}")
                errors += 1

    if errors:
        print(f"\n✗ {errors} error(s)")
        return 1
    print(f"\n✓ Plan {plan_id} valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
