#!/usr/bin/env python3
"""Restore a manifest-stamped runtime backup into a target directory.

The target must be explicitly provided and either absent or empty; this avoids
silently overwriting a live knowledge base. Use --force only after taking a
separate backup of the target. Verification runs before any target changes.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def restore(backup_dir: Path, target_root: Path, *, force: bool = False) -> dict:
    from verify_backup import verify

    verification = verify(backup_dir)
    if not verification.get("ok"):
        raise RuntimeError("backup verification failed; refusing to restore")
    if target_root.exists() and any(target_root.iterdir()) and not force:
        raise RuntimeError(f"target {target_root} is not empty; use --force only after a separate backup")
    target_root.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    mapping = {"database": "data/runtime/app.db", "chroma": "data/chroma", "uploads": "data/uploads"}
    restored: list[str] = []
    for key, relative in mapping.items():
        source_rel = manifest.get("paths", {}).get(key)
        if not source_rel:
            continue
        source = backup_dir / source_rel if not Path(source_rel).is_absolute() else Path(source_rel)
        destination = target_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
        restored.append(str(destination.relative_to(target_root)))
    return {"ok": True, "backup_dir": str(backup_dir), "target_root": str(target_root), "restored": restored, "manifest": manifest}


def main() -> int:
    ap = argparse.ArgumentParser(description="Restore a verified runtime backup")
    ap.add_argument("backup_dir", type=Path)
    ap.add_argument("--target-root", type=Path, required=True)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    try:
        result = restore(args.backup_dir, args.target_root, force=args.force)
    except Exception as exc:
        print(f"restore failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
