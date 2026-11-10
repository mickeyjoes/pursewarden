#!/usr/bin/env python3
"""Extra C1 checks using dummy data and deterministic pathname replacement."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts/g1-independent"))
import safe_import  # noqa: E402


def main():
    results = {}
    with tempfile.TemporaryDirectory(prefix="postfix-import-") as td:
        base = Path(td)
        private = base / "private"
        private.mkdir()
        secret = private / "value.json"
        secret.write_bytes(b"DUMMY_PRIVATE_SENTINEL")
        runner = base / "runner"
        runner.mkdir()
        with secret.open("rb") as f:
            (runner / "fd-link").symlink_to(f"/proc/self/fd/{f.fileno()}")
            try:
                safe_import.read_untrusted(runner, "fd-link", 1024)
            except safe_import.ImportRejected:
                results["proc_self_fd_symlink_rejected"] = True
            else:
                raise AssertionError("proc fd symlink followed")

        value = runner / "value.json"
        value.write_bytes(b"PUBLIC_ORIGINAL")
        original_fstat = os.fstat

        def swap_after_fstat(fd):
            st = original_fstat(fd)
            value.unlink()
            value.symlink_to(secret)
            return st

        with patch.object(safe_import.os, "fstat", swap_after_fstat):
            data = safe_import.read_untrusted(runner, "value.json", 1024)
        assert data == b"PUBLIC_ORIGINAL"
        results["replacement_after_fstat_keeps_original_inode"] = True

        out = runner / "out"
        out.mkdir()
        (out / "value.json").write_bytes(b"PUBLIC_DIRECTORY_ORIGINAL")
        original_open = os.open
        swapped = False

        def swap_directory_before_final_open(path, flags, *args, **kwargs):
            nonlocal swapped
            if path == "value.json" and "dir_fd" in kwargs and not swapped:
                swapped = True
                out.rename(runner / "saved-out")
                out.symlink_to(private)
            return original_open(path, flags, *args, **kwargs)

        with patch.object(safe_import.os, "open", swap_directory_before_final_open):
            data = safe_import.read_untrusted(runner, "out/value.json", 1024)
        assert data == b"PUBLIC_DIRECTORY_ORIGINAL"
        results["intermediate_replacement_keeps_open_directory"] = True
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
