"""Generate deterministic crypto test vectors for cross-checking the Dart port.

Output: JSON with known key material and the exact bytes Python produces, so
the Dart test can assert byte-for-byte equality on HKDF, signatures, sender-key
blobs, group payloads, and file-key wrapping.
"""
import base64
import json
import os
import sys

b64encode = base64.b64encode

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "client"))

from crypto.double_ratchet import derive_initial_shared_secret
from crypto.file_crypto import FileEncryptor
from crypto.key_backup import KeyBackupManager
from crypto.message_crypto import MessageEncryptor
from crypto.sender_keys import (
    encrypt_group_message,
    wrap_distribution,
    unwrap_distribution,
    serialize_blob,
    create_chain,
    _canonical,
    _INFO_DIST,
    DIST_VERSION,
)
from crypto.ratchet_facade import RatchetEncryptor
from crypto.key_generator import KeyGenerator

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Fixed key material
ED_PRIV = bytes(range(32))
X_PRIV = bytes(range(32, 64))
ALICE_X_PRIV = bytes(range(1, 33))
BOB_X_PRIV = bytes(range(33, 65))

ed_priv = KeyGenerator.load_ed25519_private_key(ED_PRIV)
ed_pub = ed_priv.public_key()
x_priv = KeyGenerator.load_x25519_private_key(X_PRIV)
x_pub = x_priv.public_key()
alice_x_priv = KeyGenerator.load_x25519_private_key(ALICE_X_PRIV)
alice_x_pub = alice_x_priv.public_key()
bob_x_priv = KeyGenerator.load_x25519_private_key(BOB_X_PRIV)
bob_x_pub = bob_x_priv.public_key()

out = {}

# --- Ed25519 signing (deterministic seed) ---
msg = b"hello world"
out["ed_sign"] = base64.b64encode(ed_priv.sign(msg)).decode()
out["ed_pub"] = base64.b64encode(ed_pub.public_bytes_raw()).decode()
out["x_pub"] = base64.b64encode(x_pub.public_bytes_raw()).decode()

# --- derive_initial_shared_secret ---
out["initial_shared"] = base64.b64encode(
    derive_initial_shared_secret(ALICE_X_PRIV, bob_x_pub.public_bytes_raw())
).decode()

# --- v1 message encrypt (MessageEncryptor) ---
enc = MessageEncryptor()
v1 = enc.encrypt_message(
    "Привет, мир!",
    recipient_x25519_pub=x_pub,
    sender_ed25519_priv=ed_priv,
    sender_x25519_pub=x_pub,
    sender_id="7",
    recipient_id="9",
)
out["v1"] = v1

# --- v2 ratchet (RatchetEncryptor) ---
rc = RatchetEncryptor()
v2 = rc.encrypt_message(
    "ratchet msg",
    peer_key="bob@example.org",
    peer_identity_x25519_pub=bob_x_pub,
    sender_ed25519_priv=ed_priv,
    sender_x25519_priv=x_priv,
    sender_id="7",
    recipient_id="9",
    store=None,
)
out["v2"] = v2

# --- sender-key group (wrap + encrypt + serialize) ---
# Fixed chain key so every dependent output (dist payload, mk, chain advance)
# is deterministic and byte-comparable with Dart.
from crypto.sender_keys import SenderChainState  # noqa: E402

FIXED_CHAIN_KEY = bytes(range(200, 232))
chain = SenderChainState(generation=0, iteration=0, chain_key=FIXED_CHAIN_KEY)
dist = wrap_distribution(chain, bob_x_pub)
chain2 = unwrap_distribution(dist, bob_x_priv)
payload = json.dumps(
    {"t": "group-payload", "v": 1, "body": "группа!", "files": {"5": "a2V5"}},
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
blob_dict, mk, new_chain = encrypt_group_message(chain2, payload)

# Deterministic distribution blob: fixed ephemeral private key so the bytes can
# be compared byte-for-byte with Dart. Verified through Python's unwrap below.
FIXED_EPH_PRIV = bytes(range(100, 132))
eph_priv = KeyGenerator.load_x25519_private_key(FIXED_EPH_PRIV)
eph_pub_bytes = eph_priv.public_key().public_bytes_raw()
recipient_pub_bytes = bob_x_pub.public_bytes_raw()
shared_secret = eph_priv.exchange(bob_x_pub)
salt = eph_pub_bytes + recipient_pub_bytes
wrapping_key = HKDF(
    algorithm=hashes.SHA256(), length=32, salt=salt, info=_INFO_DIST
).derive(shared_secret)
dist_payload = _canonical(
    {
        "v": DIST_VERSION,
        "t": "sender-key",
        "gen": chain.generation,
        "ck": b64encode(chain.chain_key).decode("ascii"),
    }
)
nonce = bytes(range(12))
ct = AESGCM(wrapping_key).encrypt(nonce, dist_payload, None)
fixed_dist_blob = b64encode(
    _canonical(
        {
            "v": DIST_VERSION,
            "ephemeral_pub": b64encode(eph_pub_bytes).decode("ascii"),
            "ct": b64encode(nonce + ct).decode("ascii"),
        }
    )
).decode("ascii")
# Sanity: our deterministic blob must unwrap to the same chain in Python.
fixed_chain2 = unwrap_distribution(fixed_dist_blob, bob_x_priv)
assert fixed_chain2.chain_key == chain2.chain_key, "fixed dist mismatch"

out["group"] = {
    "blob_dict": blob_dict,
    "serialized_blob": base64.b64encode(serialize_blob(blob_dict)).decode(),
    "payload_bytes": base64.b64encode(payload).decode(),
    "message_key": base64.b64encode(mk).decode(),
    "new_chain_key": base64.b64encode(new_chain.chain_key).decode(),
    "new_chain_iteration": new_chain.iteration,
    "fixed_dist_blob": fixed_dist_blob,
    "fixed_eph_priv": base64.b64encode(FIXED_EPH_PRIV).decode(),
    "dist_wrap_key": base64.b64encode(wrapping_key).decode(),
    "dist_payload_bytes": base64.b64encode(dist_payload).decode(),
}

# --- file key blob (v1 shape used for personal files) ---
fe = FileEncryptor()
import io
buf = io.BytesIO()
key_meta = fe.encrypt_file_streaming(
    src_path=os.path.join(os.path.dirname(__file__), "sample.txt"),
    dst=buf,
    filename="sample.txt",
    recipient_x25519_pub=x_pub,
    sender_ed25519_priv=ed_priv,
    sender_x25519_pub=x_pub,
    sender_id="7",
    recipient_id="9",
)
out["file"] = {
    **key_meta,
    "ciphertext": base64.b64encode(buf.getvalue()).decode(),
}

# --- key backup (fixed salt + nonce for byte-for-byte comparison) ---
FIXED_SALT = bytes(range(16))
FIXED_NONCE = bytes(range(16, 28))
backup_plaintext = json.dumps(
    {
        "ed25519_priv": base64.b64encode(KeyGenerator.serialize_private_key(ed_priv)).decode(),
        "x25519_priv": base64.b64encode(KeyGenerator.serialize_private_key(x_priv)).decode(),
        "version": 1,
    }
).encode()
backup_key = KeyBackupManager._derive_key("password123", FIXED_SALT)
backup_ct = AESGCM(backup_key).encrypt(FIXED_NONCE, backup_plaintext, None)
out["backup"] = base64.b64encode(FIXED_SALT + FIXED_NONCE + backup_ct).decode()
# Sanity: Python can restore its own deterministic backup.
_ed2, _x2 = KeyBackupManager.decrypt_backup(FIXED_SALT + FIXED_NONCE + backup_ct, "password123")
assert KeyGenerator.serialize_private_key(_ed2) == KeyGenerator.serialize_private_key(ed_priv)

os.makedirs(os.path.join(os.path.dirname(__file__)), exist_ok=True)
with open(os.path.join(os.path.dirname(__file__), "vectors.json"), "w") as f:
    json.dump(out, f)
print("wrote vectors.json")
