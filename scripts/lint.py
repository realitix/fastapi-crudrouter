#!/usr/bin/env python3
"""
Script de linting unifié pour fastapi-crudrouter
Usage: python scripts/lint.py [--fix] [--check-only] [tool1,tool2,...]
"""
import argparse
from pathlib import Path
import subprocess
import sys
from typing import List

PROJECT_ROOT = Path(__file__).parent.parent
SOURCE_DIRS = ["fastapi_crudrouter", "tests"]

def run_command(cmd: List[str], description: str, fix_mode: bool = False) -> bool:
    """Execute a command and return success status"""
    print(f"\n🔍 {description}...")
    print(f"Command: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False
        )

        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)

        if result.returncode == 0:
            print(f"✅ {description} passed")
            return True
        else:
            print(f"❌ {description} failed (exit code: {result.returncode})")
            return False

    except FileNotFoundError:
        print(f"❌ Tool not found for {description}")
        return False
    except Exception as e:
        print(f"❌ Error running {description}: {e}")
        return False

def run_ruff(fix_mode: bool = False, check_only: bool = False) -> bool:
    """Run ruff linter and formatter"""
    success = True

    if not check_only:
        # Run ruff check
        cmd = ["uv", "run", "ruff", "check"]
        if fix_mode:
            cmd.append("--fix")
        cmd.extend(SOURCE_DIRS)

        success &= run_command(cmd, "Ruff linting", fix_mode)

    # Run ruff format
    cmd = ["uv", "run", "ruff", "format"]
    if check_only:
        cmd.append("--check")
    cmd.extend(SOURCE_DIRS)

    success &= run_command(cmd, "Ruff formatting", fix_mode)

    return success

def run_pylint() -> bool:
    """Run pylint"""
    cmd = ["uv", "run", "pylint"] + SOURCE_DIRS
    return run_command(cmd, "Pylint analysis")

def run_mypy() -> bool:
    """Run mypy"""
    cmd = ["uv", "run", "mypy"] + SOURCE_DIRS
    return run_command(cmd, "MyPy type checking")

def main():
    parser = argparse.ArgumentParser(description="Run linting tools")
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Automatically fix issues where possible"
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only check formatting, don't apply fixes"
    )
    parser.add_argument(
        "tools",
        nargs="?",
        help="Comma-separated list of tools to run (ruff,pylint,mypy). Default: all"
    )

    args = parser.parse_args()

    # Parse tools to run
    if args.tools:
        tools = [t.strip().lower() for t in args.tools.split(",")]
    else:
        tools = ["ruff", "pylint", "mypy"]

    print(f"🚀 Running linting tools: {', '.join(tools)}")
    print(f"📁 Source directories: {', '.join(SOURCE_DIRS)}")

    results = {}

    if "ruff" in tools:
        results["ruff"] = run_ruff(args.fix, args.check_only)

    if "pylint" in tools:
        results["pylint"] = run_pylint()

    if "mypy" in tools:
        results["mypy"] = run_mypy()

    # Summary
    print("\n" + "="*50)
    print("📊 LINTING SUMMARY")
    print("="*50)

    all_passed = True
    for tool, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{tool.upper():>8}: {status}")
        all_passed &= passed

    if all_passed:
        print("\n🎉 All linting checks passed!")
        sys.exit(0)
    else:
        print("\n💥 Some linting checks failed!")
        sys.exit(1)

if __name__ == "__main__":
    main()
