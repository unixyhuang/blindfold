"""Build the public artifact ZIP from this checkout's tracked source files."""

import argparse
import fnmatch
import subprocess
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRECTORIES = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".idea", ".vscode",
    "build", "dist", "runs", "logs", "checkpoints", "weights", "downloads",
    "local_calibration",
}
EXCLUDED_FILES = (
    "*.pyc", "*.pyo", "*.log", "*.zip", "*.safetensors", "*.ckpt",
    "credentials*.json", ".DS_Store", "Thumbs.db",
)


def excluded(relative):
    if any(part in EXCLUDED_DIRECTORIES for part in relative.parts):
        return True
    name = relative.name
    if (name == ".env" or name.startswith(".env.")) and name != ".env.example":
        return True
    if relative.parts[0] == "configs" and name.startswith("local"):
        return True
    return any(fnmatch.fnmatch(name, pattern) for pattern in EXCLUDED_FILES)


def source_files():
    """Use tracked paths in a Git checkout, or files from an extracted artifact."""
    if (ROOT / ".git").exists():
        result = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--cached", "-z"],
            check=True, capture_output=True,
        )
        paths = [ROOT / value.decode("utf-8") for value in result.stdout.split(b"\0") if value]
    else:
        paths = list(ROOT.rglob("*"))
    files = []
    for path in paths:
        relative = path.relative_to(ROOT)
        if path.is_symlink() or excluded(relative) or not path.is_file():
            continue
        if not path.resolve().is_relative_to(ROOT):
            raise ValueError(f"Source path leaves the project directory: {relative}")
        files.append(path)
    return sorted(files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/blindfold-artifact.zip")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.suffix.lower() != ".zip":
        parser.error("The output filename must end in .zip.")
    files = source_files()
    if not files:
        parser.error("No source files are available to package.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="blindfold-zip-", dir=output.parent) as directory:
        staged = Path(directory) / output.name
        with zipfile.ZipFile(staged, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path, "blindfold-artifact/" + path.relative_to(ROOT).as_posix())
        with zipfile.ZipFile(staged) as archive:
            if archive.testzip() is not None:
                raise RuntimeError("The generated ZIP failed its CRC check.")
        staged.replace(output)
    print(f"Packaged {len(files)} source files into {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
