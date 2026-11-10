"""Import untrusted runner output without following runner-controlled links.

Fix for independent review finding C1 (2026-11-10): the reviewer must never resolve a path
inside a runner-writable tree with the ordinary path walker, because a runner-planted absolute
symlink resolves in the REVIEWER's mount namespace (where private files exist).

`read_untrusted` walks from a reviewer-owned root directory descriptor, one component at a
time, with O_NOFOLLOW at every step (intermediate directories and the final file). It accepts
only a regular file with a single link, bounded in size, and returns its bytes. The caller then
validates the JSON schema and stores the bytes itself; it never re-reads the runner path.
"""
import json
import os
import stat
from pathlib import PurePosixPath

O_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
O_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
SECRET_FIELDS = {"secret_key", "private_key", "secret", "seed_phrase", "mnemonic"}


class ImportRejected(Exception):
    pass


def read_untrusted(root, rel, max_bytes):
    rp = PurePosixPath(rel)
    parts = rp.parts
    if rp.is_absolute() or not parts or any(p in ("", ".", "..") for p in parts):
        raise ImportRejected(f"unsafe relative path {rel!r}")
    try:
        fd = os.open(root, O_DIR)
    except OSError as exc:
        raise ImportRejected(f"root {root}: {exc.strerror}") from exc
    try:
        for comp in parts[:-1]:
            try:
                nfd = os.open(comp, O_DIR, dir_fd=fd)
            except OSError as exc:  # ELOOP / ENOTDIR for a symlinked or non-directory component
                raise ImportRejected(f"component {comp!r}: {exc.strerror}") from exc
            os.close(fd)
            fd = nfd
        try:
            ffd = os.open(parts[-1], O_FILE, dir_fd=fd)
        except OSError as exc:
            raise ImportRejected(f"file {parts[-1]!r}: {exc.strerror}") from exc
    finally:
        os.close(fd)
    try:
        st = os.fstat(ffd)
        if not stat.S_ISREG(st.st_mode):
            raise ImportRejected(f"{rel}: not a regular file")
        if st.st_nlink != 1:
            raise ImportRejected(f"{rel}: hard-linked file ({st.st_nlink} links)")
        if st.st_size > max_bytes:
            raise ImportRejected(f"{rel}: {st.st_size} bytes exceeds {max_bytes}")
        chunks, total = [], 0
        while True:
            b = os.read(ffd, min(1 << 20, max_bytes + 1 - total))
            if not b:
                break
            chunks.append(b)
            total += len(b)
            if total > max_bytes:
                raise ImportRejected(f"{rel}: grew beyond {max_bytes} bytes")
        return b"".join(chunks)
    finally:
        os.close(ffd)


def _no_secret_fields(obj, path="$"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in SECRET_FIELDS:
                raise ImportRejected(f"secret-like field {path}.{k}")
            _no_secret_fields(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _no_secret_fields(v, f"{path}[{i}]")


def _strict_json(data):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise ImportRejected(f"duplicate JSON key {k!r}")
            out[k] = v
        return out
    try:
        return json.loads(data, object_pairs_hook=pairs,
                          parse_constant=lambda c: (_ for _ in ()).throw(ImportRejected(c)))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ImportRejected(f"invalid JSON: {exc}") from exc


def validate_runner_log(obj):
    if not (isinstance(obj, dict) and obj.get("schema") == "g1-independent/runner-log/v1"
            and isinstance(obj.get("attempts"), list) and len(obj["attempts"]) <= 64):
        raise ImportRejected("runner log schema")
    for a in obj["attempts"]:
        if not (isinstance(a, dict) and isinstance(a.get("label"), str) and isinstance(a.get("result"), dict)
                and isinstance(a["result"].get("tx_hash"), str)):
            raise ImportRejected("runner log attempt schema")


def validate_isolation(obj):
    need = {"isolation_checks": str, "forbidden_paths_exist": dict, "admin_methods_via_filter": dict,
            "direct_node_rpc_127.0.0.1": str, "visible_root_entries": list}
    if not isinstance(obj, dict) or any(not isinstance(obj.get(k), t) for k, t in need.items()):
        raise ImportRejected("isolation probe schema")
    if obj["isolation_checks"] not in ("PASS", "FAIL"):
        raise ImportRejected("isolation verdict")


def validate_capture(obj):
    if not (isinstance(obj, dict) and obj.get("schema") == "near-g1-capture/v1"
            and isinstance(obj.get("graphs"), dict) and isinstance(obj.get("status"), dict)):
        raise ImportRejected("presented capture schema")


def import_json(root, rel, max_bytes, validator):
    """Return (exact bytes, parsed object) of an untrusted runner JSON output."""
    data = read_untrusted(root, rel, max_bytes)
    obj = _strict_json(data)
    _no_secret_fields(obj)
    validator(obj)
    return data, obj
