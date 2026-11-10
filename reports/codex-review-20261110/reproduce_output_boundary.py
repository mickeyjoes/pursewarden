#!/usr/bin/env python3
"""Review-only reproduction: copy a dummy private file through a runner symlink.

Uses the production bwrap helper and the same shutil.copy operation as run_g1.py.
Never reads real keys, contacts a node, or changes project implementation files.
Run from the repository root:
    python3 reports/codex-review-20261110/reproduce_output_boundary.py
"""
import importlib.util
import json
import shlex
import shutil
import tempfile
from pathlib import Path


def main():
    repo = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "reviewed_run_g1", repo / "scripts/g1-independent/run_g1.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    base = Path(tempfile.mkdtemp(prefix="near-output-boundary-"))
    private = base / "reviewer"
    private.mkdir(mode=0o700)
    sentinel = private / "owner.key.json"
    sentinel.write_text(json.dumps({"secret_key": "DUMMY_REVIEW_SENTINEL_NOT_A_KEY"}) + "\n")
    runner = base / "runner"
    (runner / "out").mkdir(parents=True)
    public = base / "public"
    public.mkdir()

    # The absolute target is absent inside the sandbox. The symlink still survives
    # in the shared runner directory, and resolves in the reviewer's mount namespace.
    target = shlex.quote(str(sentinel))
    module.bwrap(
        runner,
        f"test ! -e {target}; ln -s {target} /runner/out/runner-log.json",
    )
    shutil.copy(runner / "out/runner-log.json", public / "runner-log.json")
    result = {
        "production_bwrap_used": True,
        "private_path_absent_inside_runner": True,
        "runner_planted_symlink": (runner / "out/runner-log.json").is_symlink(),
        "reviewer_copy_disclosed_dummy_private_file": (
            (public / "runner-log.json").read_bytes() == sentinel.read_bytes()
        ),
        "used_real_keys": False,
        "base": str(base),
    }
    assert result["runner_planted_symlink"]
    assert result["reviewer_copy_disclosed_dummy_private_file"]
    (base / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
