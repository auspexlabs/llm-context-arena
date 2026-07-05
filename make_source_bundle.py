#!/usr/bin/env python3
"""
Create a clean git-archive zip of the current repo's HEAD into ~/Documents/ProjectCode/,
and delete any .zip files in that folder older than 30 days (based on filesystem mtime).

Usage:
  python3 make_source_bundle.py
"""

import os
import sys
import shutil
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path


def run(cmd: list[str]) -> str:
    """Run a command, returning stdout (str). Raise on nonzero exit."""
    try:
        res = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return res.stdout.strip()
    except FileNotFoundError as e:
        print(f"ERROR: command not found: {cmd[0]}", file=sys.stderr)
        raise
    except subprocess.CalledProcessError as e:
        print(f"ERROR running {' '.join(cmd)}\nSTDOUT:\n{e.stdout}\nSTDERR:\n{e.stderr}", file=sys.stderr)
        raise


def ensure_git_repo() -> None:
    """Verify we're inside a git work tree."""
    try:
        out = run(["git", "rev-parse", "--is-inside-work-tree"])
    except Exception:
        print("ERROR: This does not appear to be a git repository (or git is not installed).", file=sys.stderr)
        sys.exit(2)
    if out.strip().lower() != "true":
        print("ERROR: Not inside a git work tree.", file=sys.stderr)
        sys.exit(2)


def repo_name_and_root() -> tuple[str, Path]:
    root = Path(run(["git", "rev-parse", "--show-toplevel"])).resolve()
    name = root.name
    return name, root


def warn_if_dirty() -> None:
    """Warn (non-fatal) if working tree has uncommitted changes; archive still uses HEAD."""
    status = run(["git", "status", "--porcelain"])
    if status:
        print("⚠️  Working tree has uncommitted changes. "
              "This script archives HEAD only; uncommitted edits will NOT be in the zip.",
              file=sys.stderr)


def make_output_dir() -> Path:
    out_dir = Path(os.path.expanduser("~/Documents/ProjectCode")).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def zip_head_to(out_dir: Path, repo_name: str) -> Path:
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out_zip = out_dir / f"{repo_name}-src-{ts}.zip"
    run(["git", "archive", "--format=zip", f"--output={str(out_zip)}", "HEAD"])
    if not out_zip.exists() or out_zip.stat().st_size == 0:
        print("ERROR: git archive did not produce a valid zip.", file=sys.stderr)
        sys.exit(3)
    return out_zip


def delete_old_zips(out_dir: Path, days: int = 30) -> list[Path]:
    """Delete only .zip files in out_dir older than `days` (by mtime). Return list of deleted paths."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    deleted: list[Path] = []
    for p in out_dir.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() != ".zip":
            continue
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        except Exception as e:
            print(f"Skipping (stat error): {p} -> {e}", file=sys.stderr)
            continue
        if mtime < cutoff:
            try:
                p.unlink()
                deleted.append(p)
            except Exception as e:
                print(f"Failed to delete {p}: {e}", file=sys.stderr)
    return deleted


def main() -> None:
    # 1) Preconditions
    if shutil.which("git") is None:
        print("ERROR: git not found in PATH.", file=sys.stderr)
        sys.exit(2)

    ensure_git_repo()
    warn_if_dirty()

    # 2) Prepare output dir
    out_dir = make_output_dir()

    # 3) Build archive
    repo_name, repo_root = repo_name_and_root()
    out_zip = zip_head_to(out_dir, repo_name)

    # 4) Garbage-collect old zips (mtime-based)
    deleted = delete_old_zips(out_dir, days=30)

    # 5) Report
    print(f"✅ Created archive: {out_zip} ({out_zip.stat().st_size} bytes)")
    if deleted:
        print(f"🗑️  Deleted {len(deleted)} old zip(s):")
        for p in deleted:
            print(f"   - {p}")
    else:
        print("ℹ️  No old zip files to delete.")

    # Optional: show where we archived from
    print(f"Repo root: {repo_root}")


if __name__ == "__main__":
    main()