"""Independent raw-state, policy-hash and request-digest decoding (SPEC-V1.1 section 3).

Written from the documented layout, not from the contract's or runner's decoder. Every decode
consumes its input exactly; trailing or missing bytes are evidence FAIL.
"""

import hashlib

from packages.collector import EvidenceError, b58, decode64, require

POLICY_DOMAIN = b"near-agent-vault-lab/mandate/v1\0"
REQUEST_DOMAIN = b"near-agent-vault-lab/request/v1\0"
ASSETS = {0: "NativeNear"}
CALLBACK_STATUS = {0: "Pending", 1: "CbSucceeded", 2: "CbFailed"}


class Reader:
    def __init__(self, data, what):
        self.data, self.pos, self.what = bytes(data), 0, what

    def take(self, n):
        require(self.pos + n <= len(self.data), "BORSH_TRUNCATED", self.what)
        out = self.data[self.pos:self.pos + n]
        self.pos += n
        return out

    def uint(self, n):
        return int.from_bytes(self.take(n), "little")

    def string(self):
        raw = self.take(self.uint(4))
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise EvidenceError("BORSH_UTF8", self.what, "FAIL") from exc

    def done(self):
        require(self.pos == len(self.data), "BORSH_TRAILING_BYTES",
                {"what": self.what, "consumed": self.pos, "length": len(self.data)})


def _put_str(out, s):
    raw = s.encode()
    out += len(raw).to_bytes(4, "little") + raw


def policy_body(chain_id, vault, owner, agent, budget, max_per_request, recipients,
                expires_at_ns, max_accepted_requests, asset=0):
    """Borsh of the ten SPEC policy fields, in SPEC order."""
    out = bytearray()
    for s in (chain_id, vault, owner, agent):
        _put_str(out, s)
    out += bytes([asset])
    out += int(budget).to_bytes(16, "little") + int(max_per_request).to_bytes(16, "little")
    out += len(recipients).to_bytes(4, "little")
    for r in recipients:
        _put_str(out, r)
    out += int(expires_at_ns).to_bytes(8, "little") + int(max_accepted_requests).to_bytes(4, "little")
    return bytes(out)


def policy_hash(body):
    return hashlib.sha256(POLICY_DOMAIN + body).digest()


def descriptor_policy_body(d):
    return policy_body(d["chain_id"], d["vault"], d["owner"], d["agent"], int(d["budget"]),
                       int(d["max_per_request"]), d["recipients"], int(d["expires_at_ns"]),
                       d["max_accepted_requests"])


def request_digest(vault, policy_hash_bytes, agent, request_id, recipient, amount):
    out = bytearray()
    _put_str(out, vault)
    out += policy_hash_bytes
    _put_str(out, agent)
    out += int(request_id).to_bytes(8, "little")
    _put_str(out, recipient)
    out += int(amount).to_bytes(16, "little")
    return hashlib.sha256(REQUEST_DOMAIN + bytes(out)).hexdigest()


def decode_state(raw):
    r = Reader(raw, "STATE")
    s = {"chain_id": r.string(), "vault": r.string(), "owner": r.string(), "agent": r.string()}
    asset = r.uint(1)
    require(asset in ASSETS, "STATE_ASSET", asset)
    s["asset"] = ASSETS[asset]
    s["budget"] = r.uint(16)
    s["max_per_request"] = r.uint(16)
    s["allowed_recipients"] = [r.string() for _ in range(r.uint(4))]
    s["expires_at_ns"] = r.uint(8)
    s["max_accepted_requests"] = r.uint(4)
    policy_len = r.pos
    s["policy_body_hex"] = bytes(raw[:policy_len]).hex()
    s["policy_hash"] = b58(r.take(32))
    s["storage_bound_bytes"] = r.uint(8)
    s["reserve_total"] = r.uint(16)
    s["charged"] = r.uint(16)
    s["cb_succeeded_amount"] = r.uint(16)
    s["cb_failed_amount"] = r.uint(16)
    frozen = r.uint(1)
    require(frozen in (0, 1), "STATE_BOOL", frozen)
    s["frozen"] = bool(frozen)
    s["accepted_count"] = r.uint(4)
    s["seq"] = r.uint(8)
    r.done()
    # Recompute the mandate identity from the raw policy prefix: all ten fields.
    s["policy_hash_recomputed"] = b58(policy_hash(bytes(raw[:policy_len])))
    require(s["policy_hash_recomputed"] == s["policy_hash"], "STATE_POLICY_HASH",
            {"stored": s["policy_hash"], "recomputed": s["policy_hash_recomputed"]})
    return s


def decode_record(raw):
    r = Reader(raw, "record")
    rec = {"recipient_index": r.uint(1), "amount": r.uint(16), "admission_seq": r.uint(8)}
    status = r.uint(1)
    require(status in CALLBACK_STATUS, "RECORD_STATUS", status)
    rec["callback_status"] = CALLBACK_STATUS[status]
    r.done()
    return rec


def classify_key(key):
    """Exactly three key families exist: STATE, b'r'+u64 LE, b'i'+u32 LE."""
    if key == b"STATE":
        return ("STATE", None)
    if len(key) == 9 and key[:1] == b"r":
        return ("record", int.from_bytes(key[1:], "little"))
    if len(key) == 5 and key[:1] == b"i":
        return ("index", int.from_bytes(key[1:], "little"))
    raise EvidenceError("UNKNOWN_STORAGE_KEY", key.hex(), "FAIL")


def decode_view_state(values):
    out = {"STATE": None, "records": {}, "index": {}}
    seen = set()
    for item in values:
        key, value = decode64(item["key"]), decode64(item["value"])
        require(key not in seen, "DUPLICATE_STORAGE_KEY", key.hex())
        seen.add(key)
        kind, n = classify_key(key)
        if kind == "STATE":
            out["STATE"] = decode_state(value)
        elif kind == "record":
            out["records"][n] = decode_record(value)
        else:
            require(len(value) == 8, "INDEX_VALUE", key.hex())
            out["index"][n] = int.from_bytes(value, "little")
    require(out["STATE"] is not None, "STATE_MISSING", "raw state has no STATE key")
    return out
