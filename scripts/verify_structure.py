#!/usr/bin/env python3
"""
Verify DiskForge project structure and syntax.

This script can run without external dependencies to verify the codebase.
"""

import ast
import os
import sys
from pathlib import Path


def verify_syntax(file_path: Path) -> tuple[bool, str]:
    """Verify Python file syntax."""
    try:
        with open(file_path, "r") as f:
            source = f.read()
        ast.parse(source)
        return True, "OK"
    except SyntaxError as e:
        return False, f"Syntax error: {e}"
    except Exception as e:
        return False, f"Error: {e}"


def main() -> int:
    """Main verification routine."""
    project_root = Path(__file__).parent.parent
    src_dir = project_root / "src" / "diskforge"
    tests_dir = project_root / "tests"

    print("=" * 60)
    print("DiskForge Structure Verification")
    print("=" * 60)

    # Check required directories
    required_dirs = [
        src_dir / "core",
        src_dir / "platform" / "linux",
        src_dir / "platform" / "windows",
        src_dir / "plugins",
        src_dir / "ui" / "models",
        src_dir / "ui" / "views",
        src_dir / "ui" / "widgets",
        src_dir / "cli",
        tests_dir / "unit",
        tests_dir / "integration",
        tests_dir / "gui",
    ]

    print("\nChecking directories...")
    all_dirs_ok = True
    for dir_path in required_dirs:
        exists = dir_path.exists()
        status = "✓" if exists else "✗"
        print(f"  [{status}] {dir_path.relative_to(project_root)}")
        if not exists:
            all_dirs_ok = False

    # Check required files
    required_files = [
        "pyproject.toml",
        "Makefile",
        "README.md",
        "src/diskforge/__init__.py",
        "src/diskforge/core/config.py",
        "src/diskforge/core/job.py",
        "src/diskforge/core/safety.py",
        "src/diskforge/core/models.py",
        "src/diskforge/core/session.py",
        "src/diskforge/core/logging.py",
        "src/diskforge/platform/base.py",
        "src/diskforge/platform/linux/backend.py",
        "src/diskforge/platform/windows/backend.py",
        "src/diskforge/plugins/base.py",
        "src/diskforge/cli/main.py",
        "src/diskforge/ui/main.py",
        "docs/limitations.md",
    ]

    print("\nChecking required files...")
    all_files_ok = True
    for file_rel in required_files:
        file_path = project_root / file_rel
        exists = file_path.exists()
        status = "✓" if exists else "✗"
        print(f"  [{status}] {file_rel}")
        if not exists:
            all_files_ok = False

    # Verify Python syntax
    print("\nVerifying Python syntax...")
    py_files = list((project_root / "src").rglob("*.py"))
    py_files.extend(list((project_root / "tests").rglob("*.py")))

    syntax_errors = []
    for py_file in py_files:
        ok, msg = verify_syntax(py_file)
        if not ok:
            syntax_errors.append((py_file.relative_to(project_root), msg))

    if syntax_errors:
        print("  Syntax errors found:")
        for file_path, msg in syntax_errors:
            print(f"    ✗ {file_path}: {msg}")
    else:
        print(f"  ✓ All {len(py_files)} Python files have valid syntax")

    # Count lines of code
    print("\nCode statistics...")
    total_lines = 0
    src_lines = 0
    test_lines = 0

    for py_file in py_files:
        with open(py_file, "r") as f:
            lines = len(f.readlines())
        total_lines += lines
        if "tests" in str(py_file):
            test_lines += lines
        else:
            src_lines += lines

    print(f"  Source code: {src_lines:,} lines")
    print(f"  Test code: {test_lines:,} lines")
    print(f"  Total: {total_lines:,} lines")

    # Summary
    print("\n" + "=" * 60)
    all_ok = all_dirs_ok and all_files_ok and not syntax_errors

    if all_ok:
        print("✓ All verification checks passed!")
        return 0
    else:
        print("✗ Some verification checks failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
