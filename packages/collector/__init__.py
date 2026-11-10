"""Reviewer-owned, read-only acquisition. No runner-derived discovery seeds."""

import base64
import hashlib
import ipaddress
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class EvidenceError(Exception):
    def __init__(self, code, detail, verdict="INCONCLUSIVE"):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail, self.verdict = code, detail, verdict


def require(condition, code, detail, verdict="FAIL"):
    if not condition:
        raise EvidenceError(code, detail, verdict)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE_JSON_KEY", key)
        result[key] = value
    return result


def loads(data):
    def invalid(value):
        raise EvidenceError("INVALID_JSON_NUMBER", value, "FAIL")
    return json.loads(data, object_pairs_hook=_pairs, parse_constant=invalid)


def read_json(path):
    p = Path(path)
    require(p.stat().st_size <= 64 * 1024 * 1024, "INPUT_TOO_LARGE", str(p))
    return loads(p.read_bytes())


ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58(data):
    n, result = int.from_bytes(data, "big"), ""
    while n:
        n, rem = divmod(n, 58)
        result = ALPHABET[rem] + result
    return "1" * (len(data) - len(data.lstrip(b"\0"))) + result


def hash_id(value):
    require(isinstance(value, str) and 32 <= len(value) <= 44,
            "INVALID_HASH", repr(value))
    require(all(c in ALPHABET for c in value), "INVALID_HASH", value)
    n = 0
    for c in value:
        n = n * 58 + ALPHABET.index(c)
    data = b"\0" * (len(value) - len(value.lstrip("1")))
    data += n.to_bytes((n.bit_length() + 7) // 8, "big")
    require(len(data) == 32 and b58(data) == value, "INVALID_HASH", value)
    return value


def b58decode32(value):
    """Decode a canonical base58 32-byte hash (validated by hash_id)."""
    hash_id(value)
    n = 0
    for c in value:
        n = n * 58 + ALPHABET.index(c)
    return n.to_bytes(32, "big")


def decimal(value, bits=128):
    require(isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]*", value)
            and len(value) <= (20 if bits == 64 else 39), "INVALID_DECIMAL", repr(value))
    result = int(value)
    require(result < 2**bits, "DECIMAL_OVERFLOW", value)
    return result


def account(value):
    require(isinstance(value, str) and 2 <= len(value) <= 64
            and re.fullmatch(r"[a-z0-9]+(?:[._-][a-z0-9]+)*", value),
            "INVALID_ACCOUNT", repr(value))
    return value


def decode64(value):
    return base64.b64decode(value, validate=True)


READ_METHODS = {"status", "block", "chunk", "query", "EXPERIMENTAL_genesis_config",
                "EXPERIMENTAL_protocol_config", "EXPERIMENTAL_tx_status", "EXPERIMENTAL_changes"}


class Rpc:
    """Endpoint is selected by reviewer CLI, never by presented evidence."""
    mode = "LIVE"

    def __init__(self, endpoint, network, raw_dir, timeout=10, deadline=300):
        require(network in {"sandbox", "testnet", "mainnet"}, "NETWORK_REQUIRED", network)
        u = urllib.parse.urlparse(endpoint)
        require(u.scheme in {"http", "https"} and u.hostname and not u.username
                and not u.password and not u.fragment, "INVALID_ENDPOINT", endpoint)
        if network == "sandbox":
            try:
                loopback = ipaddress.ip_address(u.hostname).is_loopback
            except ValueError:
                loopback = u.hostname == "localhost"
            require(loopback, "SANDBOX_LOOPBACK_REQUIRED", endpoint)
        self.endpoint, self.network = endpoint, network
        self.raw_dir = Path(raw_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=False)
        self.timeout, self.end = timeout, time.monotonic() + deadline
        self.count, self.bytes = 0, 0
        self.started = time.monotonic()
        # Do not inherit proxy configuration, redirects or authentication.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def call(self, method, params):
        require(method in READ_METHODS, "READ_ONLY_METHOD", method)
        require(time.monotonic() < self.end, "DEADLINE", method, "INCONCLUSIVE")
        require(self.count < 100000 and self.bytes < 256 * 1024 * 1024,
                "ACQUISITION_BOUND", "RPC count or total bytes exceeded", "INCONCLUSIVE")
        self.count += 1
        req = {"jsonrpc": "2.0", "id": self.count, "method": method, "params": params}
        record = {"request": req, "endpoint": self.endpoint, "acquired_unix_ns": time.time_ns()}
        path = self.raw_dir / f"{self.count:06d}.json"
        try:
            request = urllib.request.Request(self.endpoint, data=canonical(req),
                                             headers={"Content-Type": "application/json"})
            with self.opener.open(request, timeout=min(self.timeout, self.end-time.monotonic())) as r:
                raw = r.read(32 * 1024 * 1024 + 1)
            self.bytes += len(raw)
            require(len(raw) <= 32 * 1024 * 1024, "RESPONSE_TOO_LARGE", method, "INCONCLUSIVE")
            # Preserve exact response bytes even on schema failure.
            record["response_base64"] = base64.b64encode(raw).decode()
            require(self.bytes <= 256 * 1024 * 1024, "ACQUISITION_BOUND", "total bytes", "INCONCLUSIVE")
            response = loads(raw)
            require(response.get("jsonrpc") == "2.0" and response.get("id") == self.count,
                    "RPC_ENVELOPE", method)
            if "error" in response:
                raise EvidenceError("RPC_UNAVAILABLE", {"method": method, "params": params,
                                                       "error": response["error"]})
            require(response.get("result") is not None, "RPC_MISSING_RESULT", method, "INCONCLUSIVE")
            return response["result"]
        except (OSError, urllib.error.URLError) as exc:
            record["transport_error"] = str(exc)
            raise EvidenceError("SOURCE_UNAVAILABLE", {"method": method, "params": params,
                                                       "error": str(exc)}) from exc
        finally:
            path.write_bytes(canonical(record) + b"\n")

    def metrics(self):
        return {"rpc_count": self.count, "response_bytes": self.bytes,
                "elapsed_seconds": round(time.monotonic() - self.started, 4)}


def validate_descriptor(d):
    require(d["schema"] == "near-g1-reviewer/v1", "DESCRIPTOR_SCHEMA", d.get("schema"))
    require(d["network"] in {"sandbox", "testnet", "mainnet"}, "NETWORK_REQUIRED", d["network"])
    for name in ("genesis_block_hash", "h0_hash", "q_hash", "policy_hash"):
        hash_id(d[name])
    for name in ("vault", "owner", "agent"):
        account(d[name])
    require(len({d["vault"], d["owner"], d["agent"]}) == 3, "ROLE_COLLISION", "roles")
    require(d["vault"].count(".") == d["owner"].count(".") + 1
            and d["vault"].endswith("." + d["owner"]), "VAULT_PARENT", d["vault"])
    decimal(d["budget"])
    decimal(d["max_per_request"])
    require(0 < int(d["max_per_request"]) <= int(d["budget"]), "BUDGET", "B/M")
    require(type(d["max_blocks"]) is int and 1 <= d["max_blocks"] <= 10000,
            "BLOCK_BOUND", d["max_blocks"])
    require(type(d["max_roots"]) is int and 1 <= d["max_roots"] <= 10000,
            "ROOT_BOUND", d["max_roots"])
    require(d["shard_ids"] and all(type(x) is int and x >= 0 for x in d["shard_ids"])
            and len(d["shard_ids"]) == len(set(d["shard_ids"])), "SHARD_IDS", "invalid")
    for name in ("wasm_sha256", "node_binary_sha256", "node_config_sha256", "genesis_file_sha256", "genesis_rpc_sha256", "protocol_config_sha256"):
        require(isinstance(d[name], str) and re.fullmatch(r"[0-9a-f]{64}", d[name]),
                "DIGEST_REQUIRED", name)
    # Full ten-field policy identity (SPEC-V1.1 section 3): the verifier recomputes the hash.
    require(isinstance(d["chain_id"], str) and 0 < len(d["chain_id"].encode()) <= 64, "CHAIN_ID", d["chain_id"])
    decimal(d["expires_at_ns"], 64)
    require(type(d["max_accepted_requests"]) is int and 1 <= d["max_accepted_requests"] <= 64,
            "RECORD_QUOTA", d["max_accepted_requests"])
    require(d.get("asset", "NativeNear") == "NativeNear", "ASSET", d.get("asset"))
    for recipient in d["recipients"]:
        account(recipient)
        require("." in recipient and recipient not in {d["vault"], d["agent"], d["owner"]},
                "RECIPIENT", recipient)
    require(1 <= len(d["recipients"]) <= 8 and d["recipients"] == sorted(set(d["recipients"])),
            "RECIPIENT_ORDER", "canonical order required")


def local_provenance(d, paths):
    """Reviewer must supply these paths independently; never read paths in a bundle."""
    result = {}
    for name in ("wasm", "node_binary", "node_config", "genesis_file"):
        require(paths.get(name) is not None, "PROVENANCE_MISSING", name, "INCONCLUSIVE")
        p = Path(paths[name])
        require(p.is_file(), "PROVENANCE_MISSING", name, "INCONCLUSIVE")
        h = hashlib.sha256()
        with p.open("rb") as f:
            for part in iter(lambda: f.read(1024 * 1024), b""):
                h.update(part)
        require(h.hexdigest() == d[name + "_sha256"], "PROVENANCE_MISMATCH", name)
        result[name] = {"sha256": h.hexdigest(), "bytes": p.stat().st_size}
    return result


def protocol_shards(config):
    layout = config["shard_layout"]
    require(isinstance(layout, dict) and len(layout) == 1, "SHARD_LAYOUT_SCHEMA", layout, "INCONCLUSIVE")
    version, body = next(iter(layout.items()))
    if version == "V0":
        return list(range(body["num_shards"]))
    if version == "V1":
        return list(range(len(body["boundary_accounts"]) + 1))
    if version == "V2":
        return body["shard_ids"]
    raise EvidenceError("SHARD_LAYOUT_UNSUPPORTED", version)


def absent_at(source, aid, bh, height):
    try:
        source.call("query", {"request_type": "view_account", "account_id": aid, "block_id": bh})
    except EvidenceError as exc:
        # Only this exact typed error means absence. GC/unavailable shard/timeout
        # cannot be converted into a clean initial account inventory.
        if exc.code == "RPC_UNAVAILABLE" and isinstance(exc.detail, dict):
            cause = exc.detail.get("error", {}).get("cause", {})
            if cause.get("name") == "UNKNOWN_ACCOUNT":
                info = cause["info"]
                require(info["requested_account_id"] == aid and info["block_hash"] == bh
                        and info["block_height"] == height, "ABSENCE_CUT", aid)
                return cause
        raise
    raise EvidenceError("ACCOUNT_PREEXISTS_H0", aid, "FAIL")


def collect(source, d):
    """No bundle argument: discovery cannot depend on the runner inventory."""
    validate_descriptor(d)
    require(d["network"] == "sandbox", "PUBLIC_COMPLETENESS_UNSUPPORTED",
            "testnet/mainnet support read-only inspection only; no fresh frontier proof")
    status = source.call("status", {})
    require(status["chain_id"] == d["chain_id"], "WRONG_CHAIN", status["chain_id"])
    require(status["version"] == d["node_version"], "NODE_VERSION", status["version"])
    genesis = source.call("EXPERIMENTAL_genesis_config", {})
    require(genesis["chain_id"] == d["chain_id"], "GENESIS_CHAIN", genesis["chain_id"])
    require(digest(genesis) == d["genesis_rpc_sha256"], "GENESIS_CONFIG", digest(genesis))
    gblock = source.call("block", {"block_id": genesis["genesis_height"]})
    require(gblock["header"]["hash"] == d["genesis_block_hash"], "WRONG_GENESIS", "block hash")
    final = source.call("block", {"finality": "final"})
    # Bounded finality strategy: Q must be at or below the node's final head AND be the block the
    # node serves for Q's height on its canonical chain. This avoids spending the block budget on
    # head -> Q when acquisition happens later than Q. Then walk Q -> H0 by parent hashes
    # (skipped heights are legal).
    require(final["header"]["height"] >= d["q_height"], "Q_NOT_FINAL", final["header"]["height"], "INCONCLUSIVE")
    at_q_height = source.call("block", {"block_id": d["q_height"]})
    require(at_q_height["header"]["hash"] == d["q_hash"], "Q_NOT_CANONICAL",
            {"served": at_q_height["header"]["hash"], "expected": d["q_hash"]})
    blocks, cursor, seen = [], at_q_height, set()
    for _ in range(d["max_blocks"]):
        h = cursor["header"]
        bh = hash_id(h["hash"])
        require(bh not in seen, "BLOCK_CYCLE", bh)
        seen.add(bh)
        blocks.append(cursor)
        if bh == d["h0_hash"]:
            break
        require(h["height"] > d["h0_height"], "H0_NOT_ANCESTOR_OF_Q", bh)
        parent = source.call("block", {"block_id": hash_id(h["prev_hash"])})
        require(parent["header"]["hash"] == h["prev_hash"]
                and parent["header"]["height"] < h["height"], "BLOCK_PARENT", bh)
        cursor = parent
    else:
        raise EvidenceError("INTERVAL_BOUND", "H0 not reached")
    blocks.reverse()
    require(blocks[0]["header"]["height"] == d["h0_height"]
            and blocks[-1]["header"]["height"] == d["q_height"], "HEIGHT_INTERVAL", "anchor mismatch")
    require(len({b["header"]["epoch_id"] for b in blocks}) == 1,
            "EPOCH_TRANSITION_UNSUPPORTED", "bounded first adapter requires one epoch", "INCONCLUSIVE")
    protocol = {}
    for bh in (d["h0_hash"], d["q_hash"]):
        config = source.call("EXPERIMENTAL_protocol_config", {"block_id": bh})
        require(digest(config) == d["protocol_config_sha256"], "PROTOCOL_CONFIGURATION", bh)
        require(sorted(protocol_shards(config)) == sorted(d["shard_ids"]), "PROTOCOL_SHARDS", bh)
        protocol[bh] = config
    initial_absence = {role: absent_at(source, d[role], d["h0_hash"], d["h0_height"])
                       for role in ("vault", "agent")}
    chunks, roots, root_blocks = {}, {}, {}
    for block in blocks[1:]:
        headers, height = block["chunks"], block["header"]["height"]
        require(len(headers) == len(d["shard_ids"])
                and sorted(c["shard_id"] for c in headers) == sorted(d["shard_ids"]),
                "INCOMPLETE_SHARDS", block["header"]["hash"], "INCONCLUSIVE")
        mask = block["header"]["chunk_mask"]
        require(len(mask) == len(headers), "CHUNK_MASK", "length")
        for index, header in enumerate(headers):
            included = header["height_included"] == height
            require(type(mask[index]) is bool and mask[index] == included
                    and header["height_included"] <= height, "CHUNK_INCLUSION", header)
            if not included:
                continue
            ch = hash_id(header["chunk_hash"])
            require(ch not in chunks, "REPEATED_NEW_CHUNK", ch)
            chunk = source.call("chunk", {"chunk_id": ch})
            for field in ("chunk_hash", "shard_id", "height_created"):
                require(chunk["header"].get(field) == header.get(field), "CHUNK_HEADER", field)
            # nearcore 2.13.4 serves height_included = 0 for a chunk fetched by hash; the inclusion
            # height is bound by the block's own chunk header above. Any other value must match.
            require(chunk["header"]["height_included"] in (0, header["height_included"]),
                    "CHUNK_HEADER", "height_included")
            chunks[ch] = chunk
            for tx in chunk["transactions"]:
                txid = hash_id(tx["hash"])
                account(tx["signer_id"])
                require(txid not in roots, "DUPLICATE_ROOT", txid)
                require(len(roots) < d["max_roots"], "ROOT_BOUND", "too many", "INCONCLUSIVE")
                roots[txid] = tx
                root_blocks[txid] = block["header"]["hash"]
    graphs = {}
    for txid, tx in roots.items():
        graph = source.call("EXPERIMENTAL_tx_status", {"tx_hash": txid,
                            "sender_account_id": tx["signer_id"], "wait_until": "FINAL"})
        require(graph["transaction"] == tx, "TRANSACTION_MISMATCH", txid)
        graphs[txid] = graph
    q, vault = d["q_hash"], d["vault"]
    queries = {}
    for role, aid in (("vault", vault), ("agent", d["agent"])):
        for kind in ("view_account", "view_code", "view_access_key_list"):
            key = role + "/" + kind
            try:
                queries[key] = source.call("query", {"request_type": kind, "account_id": aid, "block_id": q})
            except EvidenceError as exc:
                cause = exc.detail.get("error", {}).get("cause", {}) if isinstance(exc.detail, dict) else {}
                if role == "agent" and kind == "view_code" and exc.code == "RPC_UNAVAILABLE" and cause.get("name") == "NO_CONTRACT_CODE":
                    info = cause["info"]
                    require(info["contract_account_id"] == aid and info["block_hash"] == q
                            and info["block_height"] == d["q_height"], "CODE_ABSENCE_CUT", aid)
                    # Retain the typed error; do not invent an empty code body.
                    queries[key] = {"block_hash": q, "block_height": d["q_height"], "absence_error": cause}
                else:
                    raise
    queries["vault/view_state"] = source.call("query", {"request_type": "view_state", "account_id": vault,
                                              "prefix_base64": "", "include_proof": True, "block_id": q})
    for method in ("get_admissions", "get_mandate"):
        queries[method] = source.call("query", {"request_type": "call_function", "account_id": vault,
                                     "method_name": method, "args_base64": "e30=", "block_id": q})
    history = []
    for block in blocks[1:]:
        bh = block["header"]["hash"]
        for kind in ("account_changes", "all_access_key_changes", "contract_code_changes", "data_changes"):
            params = {"block_id": bh, "changes_type": kind, "account_ids": [vault, d["agent"]]}
            if kind == "data_changes":
                params["key_prefix_base64"] = ""
            change = source.call("EXPERIMENTAL_changes", params)
            require(change["block_hash"] == bh, "HISTORY_BLOCK", bh)
            history.append({"kind": kind, "block_hash": bh, "result": change})
    return {"schema": "near-g1-capture/v1", "mode": source.mode, "descriptor_sha256": digest(d),
            "status": status, "genesis": genesis, "genesis_block": gblock,
            "final_head": final, "blocks": blocks, "protocol": protocol, "initial_absence": initial_absence, "chunks": chunks,
            "root_blocks": root_blocks, "graphs": graphs, "queries": queries, "history": history}
