"""Commit and push this artifact to its GitHub repository."""

import argparse
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPOSITORY = "https://github.com/unixyhuang/blindfold.git"


def git(*arguments, check=True, capture=False):
    return subprocess.run(
        ["git", "-C", str(ROOT), *arguments],
        check=check, text=True, capture_output=capture,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--message", default="Update artifact")
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    args = parser.parse_args()

    if not (ROOT / ".git").exists():
        git("init", "-b", "main")

    origin = git("remote", "get-url", "origin", check=False, capture=True)
    if origin.returncode != 0:
        git("remote", "add", "origin", args.repository)
    elif origin.stdout.strip() != args.repository:
        raise RuntimeError(
            f"origin is already set to {origin.stdout.strip()}. "
            "Pass --repository with that URL if it is the intended destination."
        )

    branch = git("symbolic-ref", "--quiet", "--short", "HEAD", capture=True).stdout.strip()
    git("add", "--all", "--", ".")
    staged = git("diff", "--cached", "--quiet", check=False)
    if staged.returncode == 1:
        git("commit", "-m", args.message)
    elif staged.returncode != 0:
        raise RuntimeError("Could not inspect staged changes.")

    git("push", "--set-upstream", "origin", branch)
    print(f"Synchronized {branch} to {args.repository}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError, RuntimeError) as error:
        print(f"Synchronization stopped: {error}")
        raise SystemExit(1)
