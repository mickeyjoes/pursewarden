"""Regression for independent review finding C1 (2026-11-10): runner-controlled links must never
make the reviewer read (and publish) a reviewer-only file. Uses a DUMMY secret only."""
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts/g1-independent"))
from safe_import import (ImportRejected, import_json, read_untrusted,  # noqa: E402
                         validate_capture, validate_isolation, validate_runner_log)

DUMMY = b'{"secret_key": "DUMMY_REGRESSION_SENTINEL_NOT_A_KEY"}\n'
LOG = {"schema": "g1-independent/runner-log/v1", "attempts": [{"label": "x", "result": {"tx_hash": "abc"}}]}


def bwrap_works():
    if not shutil.which("bwrap"):
        return False
    return subprocess.run(["bwrap", "--unshare-all", "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin",
                           "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
                           "/bin/true"], capture_output=True).returncode == 0


class SafeImportUnit(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="c1-unit-"))
        self.private = self.base / "reviewer"
        self.private.mkdir()
        self.secret = self.private / "owner.key.json"
        self.secret.write_bytes(DUMMY)
        self.runner = self.base / "runner"
        (self.runner / "out").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.base)

    def test_regular_file_is_imported_exactly(self):
        (self.runner / "out/runner-log.json").write_text(json.dumps(LOG))
        data, obj = import_json(self.runner, "out/runner-log.json", 1 << 20, validate_runner_log)
        self.assertEqual(obj, LOG)
        self.assertEqual(data, (self.runner / "out/runner-log.json").read_bytes())

    def test_final_component_symlink_is_rejected(self):
        os.symlink(self.secret, self.runner / "out/runner-log.json")
        with self.assertRaises(ImportRejected):
            read_untrusted(self.runner, "out/runner-log.json", 1 << 20)

    def test_intermediate_directory_symlink_is_rejected(self):
        shutil.rmtree(self.runner / "out")
        os.symlink(self.private, self.runner / "out")
        with self.assertRaises(ImportRejected):
            read_untrusted(self.runner, "out/owner.key.json", 1 << 20)

    def test_symlinked_root_is_rejected(self):
        link = self.base / "root-link"
        os.symlink(self.private, link)
        with self.assertRaises(ImportRejected):
            read_untrusted(link, "owner.key.json", 1 << 20)

    def test_hard_link_is_rejected(self):
        os.link(self.secret, self.runner / "out/runner-log.json")
        with self.assertRaises(ImportRejected):
            read_untrusted(self.runner, "out/runner-log.json", 1 << 20)

    def test_fifo_is_rejected_without_blocking(self):
        os.mkfifo(self.runner / "out/runner-log.json")
        with self.assertRaises(ImportRejected):
            read_untrusted(self.runner, "out/runner-log.json", 1 << 20)

    def test_oversize_and_path_tricks_are_rejected(self):
        (self.runner / "out/big.json").write_bytes(b" " * 2048)
        for rel in ("out/big.json",):
            with self.assertRaises(ImportRejected):
                read_untrusted(self.runner, rel, 1024)
        for rel in ("../reviewer/owner.key.json", str(self.secret), "", "out/./x", "out//x"):
            with self.assertRaises(ImportRejected):
                read_untrusted(self.runner, rel, 1 << 20)

    def test_schema_and_secret_fields_are_validated(self):
        (self.runner / "out/a.json").write_bytes(DUMMY)
        with self.assertRaises(ImportRejected):
            import_json(self.runner, "out/a.json", 1 << 20, validate_runner_log)
        bad = dict(LOG, attempts=[{"label": "x", "result": {"tx_hash": "a"}, "private_key": "k"}])
        (self.runner / "out/b.json").write_text(json.dumps(bad))
        with self.assertRaises(ImportRejected):
            import_json(self.runner, "out/b.json", 1 << 20, validate_runner_log)
        (self.runner / "out/c.json").write_text('{"schema": 1, "schema": 2}')
        with self.assertRaises(ImportRejected):
            import_json(self.runner, "out/c.json", 1 << 20, validate_capture)
        (self.runner / "out/d.json").write_text(json.dumps({"isolation_checks": "MAYBE"}))
        with self.assertRaises(ImportRejected):
            import_json(self.runner, "out/d.json", 1 << 20, validate_isolation)


@unittest.skipUnless(bwrap_works(), "bubblewrap unavailable")
class SandboxPlantedLinks(unittest.TestCase):
    """End-to-end through the PRODUCTION sandbox helper: the hostile runner plants links inside
    the sandbox to a reviewer-only dummy file; the reviewer import must refuse them."""

    def setUp(self):
        spec = importlib.util.spec_from_file_location("run_g1", REPO / "scripts/g1-independent/run_g1.py")
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        if not self.mod.ACTOR.exists():
            self.mod.ACTOR = Path("/usr/bin/true")  # the actor binary is irrelevant to this check
        self.base = Path(tempfile.mkdtemp(prefix="c1-e2e-"))
        self.private = self.base / "reviewer"
        self.private.mkdir(mode=0o700)
        self.secret = self.private / "owner.key.json"
        self.secret.write_bytes(DUMMY)
        self.runner = self.base / "runner"
        (self.runner / "out").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.base)

    def plant(self, script):
        self.mod.sandbox(script, rw=[(self.runner, "/runner")])

    def test_final_component_link_planted_in_sandbox(self):
        t = shlex.quote(str(self.secret))
        self.plant(f"test ! -e {t}; ln -s {t} /runner/out/runner-log.json")
        self.assertTrue((self.runner / "out/runner-log.json").is_symlink())
        with self.assertRaises(ImportRejected):
            import_json(self.runner, "out/runner-log.json", 1 << 20, validate_runner_log)

    def test_intermediate_directory_link_planted_in_sandbox(self):
        t = shlex.quote(str(self.private))
        self.plant(f"test ! -e {t}; rm -rf /runner/out; ln -s {t} /runner/out")
        self.assertTrue((self.runner / "out").is_symlink())
        with self.assertRaises(ImportRejected):
            read_untrusted(self.runner, "out/owner.key.json", 1 << 20)

    def test_socket_directory_is_read_only_inside(self):
        sock = self.base / "sock"
        sock.mkdir()
        with self.assertRaises(subprocess.CalledProcessError):
            self.mod.sandbox("ln -s /x /sock/planted", ro=[(sock, "/sock")])
        self.assertEqual(list(sock.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
