"""Minimal NIP-01 event + BIP-340 Schnorr primitives (F008).

Stdlib-only implementation of the pieces the Buzz gate bridge needs:

* x-only secp256k1 public keys
* BIP-340 Schnorr sign / verify (deterministic aux=0 path for vectors)
* NIP-01 event-id computation and structure validation

No relay client, no bech32 (npub/nsec) decoding — callers pass hex.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# secp256k1 curve parameters
_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
_GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8


def _mod_inv(a: int, m: int) -> int:
    return pow(a % m, -1, m)


def _point_add(
    p1: tuple[int, int] | None, p2: tuple[int, int] | None
) -> tuple[int, int] | None:
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % _P == 0:
        return None
    if x1 == x2 and y1 == y2:
        lam = (3 * x1 * x1 * _mod_inv(2 * y1, _P)) % _P
    else:
        lam = ((y2 - y1) * _mod_inv(x2 - x1, _P)) % _P
    x3 = (lam * lam - x1 - x2) % _P
    y3 = (lam * (x1 - x3) - y1) % _P
    return x3, y3


def _point_mul(k: int, point: tuple[int, int] | None = None) -> tuple[int, int] | None:
    if point is None:
        point = (_GX, _GY)
    r: tuple[int, int] | None = None
    addend: tuple[int, int] | None = point
    while k:
        if k & 1:
            r = _point_add(r, addend)
        addend = _point_add(addend, addend)
        k >>= 1
    return r


def _bytes_from_int(x: int) -> bytes:
    return x.to_bytes(32, "big")


def _int_from_bytes(b: bytes) -> int:
    return int.from_bytes(b, "big")


def _tagged_hash(tag: str, *msgs: bytes) -> bytes:
    tag_hash = hashlib.sha256(tag.encode("utf-8")).digest()
    h = hashlib.sha256()
    h.update(tag_hash)
    h.update(tag_hash)
    for m in msgs:
        h.update(m)
    return h.digest()


def _has_even_y(point: tuple[int, int]) -> bool:
    return point[1] % 2 == 0


def _lift_x(x: int) -> tuple[int, int] | None:
    if x >= _P:
        return None
    y_sq = (pow(x, 3, _P) + 7) % _P
    y = pow(y_sq, (_P + 1) // 4, _P)
    if pow(y, 2, _P) != y_sq:
        return None
    if y % 2 != 0:
        y = _P - y
    return x, y


def _normalize_seckey(seckey: int | bytes | str) -> int:
    if isinstance(seckey, int):
        d = seckey
    elif isinstance(seckey, bytes):
        d = _int_from_bytes(seckey)
    else:
        d = int(seckey, 16)
    if not (1 <= d <= _N - 1):
        raise ValueError("invalid seckey")
    return d


def pubkey_from_seckey(seckey: int | bytes | str) -> str:
    """Return the 32-byte x-only public key as lowercase hex."""
    d = _normalize_seckey(seckey)
    point = _point_mul(d)
    assert point is not None
    return _bytes_from_int(point[0]).hex()


def schnorr_sign(
    msg: bytes,
    seckey: int | bytes | str,
    aux_rand: bytes | None = None,
) -> bytes:
    """BIP-340 Schnorr signature. ``aux_rand`` defaults to 32 zero bytes
    (matches BIP-340 test vector 0 when seckey=3 and msg=0…0)."""
    if len(msg) != 32:
        raise ValueError("msg must be 32 bytes")
    if aux_rand is None:
        aux_rand = bytes(32)
    if len(aux_rand) != 32:
        raise ValueError("aux_rand must be 32 bytes")

    d0 = _normalize_seckey(seckey)
    p = _point_mul(d0)
    assert p is not None
    d = d0 if _has_even_y(p) else _N - d0
    t = _bytes_from_int(d ^ _int_from_bytes(_tagged_hash("BIP0340/aux", aux_rand)))
    px = _bytes_from_int(p[0])
    k0 = _int_from_bytes(_tagged_hash("BIP0340/nonce", t, px, msg)) % _N
    if k0 == 0:
        raise RuntimeError("failure (k=0)")
    r = _point_mul(k0)
    assert r is not None
    k = k0 if _has_even_y(r) else _N - k0
    e = (
        _int_from_bytes(_tagged_hash("BIP0340/challenge", _bytes_from_int(r[0]), px, msg))
        % _N
    )
    sig = _bytes_from_int(r[0]) + _bytes_from_int((k + e * d) % _N)
    if not schnorr_verify(msg, px, sig):
        raise RuntimeError("signature verification failed after signing")
    return sig


def schnorr_verify(msg: bytes, pubkey: bytes | str, sig: bytes) -> bool:
    """BIP-340 Schnorr verify. ``pubkey`` is 32-byte x-only (bytes or hex)."""
    if len(msg) != 32 or len(sig) != 64:
        return False
    if isinstance(pubkey, str):
        try:
            pubkey_b = bytes.fromhex(pubkey)
        except ValueError:
            return False
    else:
        pubkey_b = pubkey
    if len(pubkey_b) != 32:
        return False
    px = _int_from_bytes(pubkey_b)
    p = _lift_x(px)
    if p is None:
        return False
    r = _int_from_bytes(sig[:32])
    s = _int_from_bytes(sig[32:])
    if r >= _P or s >= _N:
        return False
    e = (
        _int_from_bytes(_tagged_hash("BIP0340/challenge", sig[:32], pubkey_b, msg)) % _N
    )
    # R = s*G - e*P
    r1 = _point_mul(s)
    r2 = _point_mul(e, p)
    if r2 is not None:
        r2 = (r2[0], _P - r2[1])  # negate
    r_point = _point_add(r1, r2)
    if r_point is None or not _has_even_y(r_point) or r_point[0] != r:
        return False
    return True


def compute_event_id(event: dict[str, Any]) -> str:
    """NIP-01 event id: sha256 of the serialized [0, pubkey, created_at, kind, tags, content]."""
    payload = [
        0,
        event["pubkey"],
        int(event["created_at"]),
        int(event["kind"]),
        event.get("tags") or [],
        event.get("content") or "",
    ]
    serialized = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def validate_event_structure(event: Any) -> str | None:
    """Return an error message if the event is structurally invalid, else None."""
    if not isinstance(event, dict):
        return "event must be an object"
    for key in ("id", "pubkey", "created_at", "kind", "tags", "content", "sig"):
        if key not in event:
            return f"event missing field {key!r}"
    if not isinstance(event["id"], str) or len(event["id"]) != 64:
        return "event.id must be 64-char hex"
    if not isinstance(event["pubkey"], str) or len(event["pubkey"]) != 64:
        return "event.pubkey must be 64-char hex"
    if not isinstance(event["created_at"], int) or isinstance(event["created_at"], bool):
        return "event.created_at must be an int"
    if not isinstance(event["kind"], int) or isinstance(event["kind"], bool):
        return "event.kind must be an int"
    if not isinstance(event["tags"], list):
        return "event.tags must be a list"
    for tag in event["tags"]:
        if not isinstance(tag, list) or not all(isinstance(x, str) for x in tag):
            return "event.tags entries must be string arrays"
    if not isinstance(event["content"], str):
        return "event.content must be a string"
    if not isinstance(event["sig"], str) or len(event["sig"]) != 128:
        return "event.sig must be 128-char hex"
    try:
        bytes.fromhex(event["id"])
        bytes.fromhex(event["pubkey"])
        bytes.fromhex(event["sig"])
    except ValueError:
        return "event hex fields must be valid hex"
    return None


def verify_event(event: dict[str, Any]) -> bool:
    """True when structure is valid, id matches NIP-01, and BIP-340 sig verifies."""
    if validate_event_structure(event) is not None:
        return False
    if compute_event_id(event) != event["id"].lower():
        return False
    try:
        msg = bytes.fromhex(event["id"])
        sig = bytes.fromhex(event["sig"])
    except ValueError:
        return False
    return schnorr_verify(msg, event["pubkey"], sig)


__all__ = [
    "compute_event_id",
    "pubkey_from_seckey",
    "schnorr_sign",
    "schnorr_verify",
    "validate_event_structure",
    "verify_event",
]
