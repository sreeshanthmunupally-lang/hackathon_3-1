import sys
import os
import json
import yaml
import subprocess
from pathlib import Path


def run_check(name, func):
    print(f"Running Check: {name}...", end="")
    sys.stdout.flush()
    try:
        success, msg = func()
        if success:
            print(" [PASS]")
            return True
        else:
            print(" [FAIL]")
            print(f"  Error: {msg}")
            return False
    except Exception as e:
        print(" [ERROR]")
        print(f"  Exception occurred: {e}")
        return False


# Check 1: Trailing Whitespaces
def check_trailing_whitespace():
    bad_files = []
    for root, _, files in os.walk("src"):
        for file in files:
            if file.endswith(".py"):
                path = Path(root) / file
                lines = path.read_text(encoding="utf-8").splitlines()
                for i, line in enumerate(lines):
                    if line.endswith(" ") or line.endswith("\t"):
                        bad_files.append(f"{path}:{i + 1}")
                        break
    if bad_files:
        return False, f"Found trailing whitespaces in: {', '.join(bad_files[:5])}"
    return True, ""


# Check 2: Verify Python AST (Compile check)
def check_ast_compilation():
    res = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", "src"], capture_output=True
    )
    if res.returncode != 0:
        return False, res.stderr.decode("utf-8")
    return True, ""


# Check 3: YAML validator
def check_yaml_files():
    for root, _, files in os.walk("."):
        if ".git" in root or ".venv" in root:
            continue
        for file in files:
            if file.endswith((".yml", ".yaml")):
                path = Path(root) / file
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        yaml.safe_load(f)
                except Exception as e:
                    return False, f"Invalid YAML in {path}: {e}"
    return True, ""


# Check 4: JSON validator
def check_json_files():
    for root, _, files in os.walk("."):
        if ".git" in root or ".venv" in root or "data" in root:
            continue
        for file in files:
            if file.endswith(".json"):
                path = Path(root) / file
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        json.load(f)
                except Exception as e:
                    return False, f"Invalid JSON in {path}: {e}"
    return True, ""


# Check 5: Merge conflict markers checker
def check_conflict_markers():
    conflict_markers = ["<<<<<<<", "=======", ">>>>>>>"]
    for root, _, files in os.walk("src"):
        for file in files:
            if file.endswith(".py"):
                path = Path(root) / file
                content = path.read_text(encoding="utf-8")
                for marker in conflict_markers:
                    if marker in content:
                        return False, f"Conflict marker '{marker}' found in {path}"
    return True, ""


# Check 6: Large file check (Prevent GGUF/WAV binaries from entering git history)
def check_large_files():
    limit_kb = 5000
    for root, _, files in os.walk("."):
        if ".git" in root or ".venv" in root or ".models" in root or "data" in root:
            continue
        for file in files:
            path = Path(root) / file
            size_kb = path.stat().st_size / 1024
            if size_kb > limit_kb:
                return (
                    False,
                    f"File {path} is too large ({size_kb:.2f}KB). Max allowed: {limit_kb}KB",
                )
    return True, ""


def main():
    checks = {
        "Trailing Whitespace Check": check_trailing_whitespace,
        "Python AST Compilation Check": check_ast_compilation,
        "YAML Syntax Validation": check_yaml_files,
        "JSON Syntax Validation": check_json_files,
        "Git Conflict Markers Check": check_conflict_markers,
        "Large File Limits Check": check_large_files,
    }

    all_passed = True
    for name, func in checks.items():
        if not run_check(name, func):
            all_passed = False

    if not all_passed:
        print("\nRepository Audit failed.")
        sys.exit(1)

    print("\nAll 6 Repository Audit checks passed successfully.")
    sys.exit(0)


if __name__ == "__main__":
    main()
