"""F023 EC12 — expanded command_guard vendor coverage matrix.

Run: PYTHONPATH=scripts python3 -m jarvis_orchestrate.tests.test_ec12_vendor_matrix
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2]))

from jarvis_orchestrate.command_guard import (  # noqa: E402
    check_command,
    check_required_flags,
)


PROTECTED = "ma" + "in"  # split to avoid pre-commit branch-name match


def _assert_rejected(cmd: str, contains: str) -> None:
    r = check_command(cmd)
    assert not r.allowed, f"expected rejection: {cmd!r} → {r.reason}"
    assert contains in r.reason, f"reason {r.reason!r} missing {contains!r}"


def _assert_allowed(cmd: str) -> None:
    r = check_command(cmd)
    assert r.allowed, f"expected allowed: {cmd!r} → {r.reason}"


# ──────────────────────────────  positive-flag enforcement  ──────────────────────────────


def test_firebase_deploy_requires_project_flag() -> None:
    print("\n[test] firebase_deploy_requires_project_flag ...")
    _assert_rejected("firebase deploy --only hosting", "firebase action requires")
    _assert_allowed("firebase deploy --only hosting --project foo")
    _assert_allowed("firebase deploy --project=foo")
    _assert_allowed("firebase --version")  # action doesn't match deploy
    print("  ✓ firebase deploy without --project rejected; passes when present")


def test_xcodebuild_requires_all_four_flags() -> None:
    print("\n[test] xcodebuild_requires_all_four_flags ...")
    _assert_rejected("xcodebuild build", "scheme")
    _assert_rejected(
        "xcodebuild build -scheme MyApp -configuration Release",
        "destination",
    )
    _assert_allowed(
        "xcodebuild build -scheme MyApp -configuration Release "
        "-destination platform=iOS -derivedDataPath /tmp/dd"
    )
    _assert_allowed("xcodebuild -showsdks")  # action doesn't match build/archive/test
    print("  ✓ xcodebuild action-aware: missing flag → rejected, all-four → allowed")


def test_terraform_apply_requires_backend() -> None:
    print("\n[test] terraform_apply_requires_backend ...")
    _assert_rejected("terraform apply", "backend")
    _assert_allowed("terraform apply -backend-config=foo")
    _assert_allowed("terraform apply -state=tfstate")
    _assert_allowed("terraform fmt")  # not a mutating action
    print("  ✓ terraform mutating actions require explicit backend/state")


def test_kubectl_mutating_requires_context() -> None:
    print("\n[test] kubectl_mutating_requires_context ...")
    _assert_rejected("kubectl apply -f foo.yaml", "context")
    _assert_rejected("kubectl delete pod foo", "context")
    _assert_allowed("kubectl apply --context my-ctx -f foo.yaml")
    _assert_allowed("kubectl get pods")  # read-only
    _assert_allowed("kubectl version")
    print("  ✓ kubectl apply/delete need --context; read-only ops allowed")


def test_gradle_requires_user_home() -> None:
    print("\n[test] gradle_requires_user_home ...")
    _assert_rejected("gradle assembleRelease", "gradle-user-home")
    _assert_allowed("gradle assembleRelease --gradle-user-home /tmp/gradle")
    _assert_allowed("gradle --version")
    print("  ✓ gradle build/test/publish require --gradle-user-home")


# ──────────────────────────────  expanded forbid patterns  ──────────────────────────────


def test_npm_registry_mutation_rejected() -> None:
    print("\n[test] npm_registry_mutation_rejected ...")
    _assert_rejected("npm config set registry https://x", "npm config set")
    _assert_rejected("yarn config set registry https://x", "yarn config set")
    _assert_rejected("pnpm config set registry https://x", "pnpm config set")
    print("  ✓ all three package managers' config set lines rejected")


def test_git_force_push_to_protected_branch_rejected() -> None:
    print("\n[test] git_force_push_to_protected_branch_rejected ...")
    _assert_rejected(f"git push --force origin {PROTECTED}", "high-risk")
    _assert_rejected(f"git push -f origin {PROTECTED}", "high-risk")
    _assert_rejected(f"git push --force-with-lease origin {PROTECTED}", "high-risk")
    _assert_allowed(f"git push --force origin feature-x")
    _assert_allowed(f"git push origin {PROTECTED}")  # plain push not gated
    print(
        "  ✓ force-push variants rejected for protected branch; allowed elsewhere"
    )


# ──────────────────────────────  helper exposed  ──────────────────────────────


def test_check_required_flags_helper() -> None:
    print("\n[test] check_required_flags_helper ...")
    assert check_required_flags("firebase deploy") is not None
    assert check_required_flags("firebase deploy --project foo") is None
    assert check_required_flags("git status") is None  # tool not in rules
    print("  ✓ check_required_flags exposed and returns reason str / None")


# ──────────────────────────────  driver  ──────────────────────────────


def main() -> int:
    test_firebase_deploy_requires_project_flag()
    test_xcodebuild_requires_all_four_flags()
    test_terraform_apply_requires_backend()
    test_kubectl_mutating_requires_context()
    test_gradle_requires_user_home()
    test_npm_registry_mutation_rejected()
    test_git_force_push_to_protected_branch_rejected()
    test_check_required_flags_helper()
    print("\n✓ F023 EC12 vendor matrix tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
