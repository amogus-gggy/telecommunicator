"""
Tests for the Signal-style Double Ratchet E2EE.

Covers the core state machine (convergence, out-of-order delivery, PN handling,
skip bounds), the facade (roundtrip, own-copy decrypt, version routing and v1
fallback, signature-before-state, consumed keys), session healing (simultaneous
init, peer state loss), and at-rest persistence.

Run with: python -m pytest tests/client/test_double_ratchet.py -q
"""

import base64
import copy

import pytest
from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from client.crypto.double_ratchet import (
    KeyConsumedError,
    MAX_SKIP,
    TooFarAheadError,
    init_alice,
    init_bob,
    ratchet_decrypt,
    ratchet_encrypt,
)
from client.crypto.key_generator import KeyGenerator
from client.crypto.message_crypto import MessageDecryptor, MessageEncryptor
from client.crypto.message_store import PlaintextMessageStore
from client.crypto.ratchet_facade import (
    RatchetDecryptor,
    RatchetEncryptor,
    peek_blob_version,
)
from client.crypto.ratchet_session_store import RatchetSessionStore


class _MemStorage:
    """Minimal in-memory stand-in for LocalStorage (get/set key-value)."""

    def __init__(self):
        self._data = {}

    def get(self, key):
        return self._data.get(key)

    def set(self, key, value):
        self._data[key] = value


def _x25519():
    return X25519PrivateKey.generate()


def _make_store(identity_x_priv, account):
    return RatchetSessionStore(
        _MemStorage(), identity_x_priv.private_bytes_raw(), account
    )


def _decrypt(dec, data, peer_key, recip_x, sender_ed_pub, sender_x_pub, store):
    return dec.decrypt_message(
        {"blob": data["blob"], "signature": data["signature"]},
        peer_key=peer_key,
        recipient_x25519_priv=recip_x,
        sender_ed25519_pub=sender_ed_pub,
        sender_x25519_pub=sender_x_pub,
        store=store,
    )


class TestRatchetCore:
    """Pure state-machine behaviour."""

    def _pair(self):
        alice_x, bob_x = _x25519(), _x25519()
        return alice_x, bob_x

    def test_bootstrap_convergence(self):
        alice_x, bob_x = self._pair()
        a = init_alice(alice_x.private_bytes_raw(), bob_x.public_key().public_bytes_raw())
        header, mk_a = ratchet_encrypt(a, b"hello")
        b = init_bob(
            bob_x.private_bytes_raw(),
            alice_x.public_key().public_bytes_raw(),
            base64.b64decode(header["dh"]),
        )
        mk_b = ratchet_decrypt(b, header)
        assert mk_a == mk_b

    def test_ping_pong_advances_dh(self):
        alice_x, bob_x = self._pair()
        a = init_alice(alice_x.private_bytes_raw(), bob_x.public_key().public_bytes_raw())
        h1, mk1 = ratchet_encrypt(a, b"m1")
        b = init_bob(
            bob_x.private_bytes_raw(),
            alice_x.public_key().public_bytes_raw(),
            base64.b64decode(h1["dh"]),
        )
        assert ratchet_decrypt(b, h1) == mk1

        dh_seen = {h1["dh"]}
        # B -> A
        h2, mk2 = ratchet_encrypt(b, b"m2")
        assert ratchet_decrypt(a, h2) == mk2
        dh_seen.add(h2["dh"])
        # A -> B
        h3, mk3 = ratchet_encrypt(a, b"m3")
        assert ratchet_decrypt(b, h3) == mk3
        dh_seen.add(h3["dh"])
        # Each reply rotates the sender's ratchet public key.
        assert len(dh_seen) == 3

    def test_out_of_order(self):
        alice_x, bob_x = self._pair()
        a = init_alice(alice_x.private_bytes_raw(), bob_x.public_key().public_bytes_raw())
        msgs = [ratchet_encrypt(a, b"m%d" % i) for i in range(5)]
        b = init_bob(
            bob_x.private_bytes_raw(),
            alice_x.public_key().public_bytes_raw(),
            base64.b64decode(msgs[0][0]["dh"]),
        )
        for idx in [0, 2, 1, 4, 3]:
            header, mk = msgs[idx]
            assert ratchet_decrypt(b, dict(header)) == mk

    def test_consumed_key_raises(self):
        alice_x, bob_x = self._pair()
        a = init_alice(alice_x.private_bytes_raw(), bob_x.public_key().public_bytes_raw())
        h, mk = ratchet_encrypt(a, b"m0")
        b = init_bob(
            bob_x.private_bytes_raw(),
            alice_x.public_key().public_bytes_raw(),
            base64.b64decode(h["dh"]),
        )
        ratchet_decrypt(b, dict(h))
        with pytest.raises(KeyConsumedError):
            ratchet_decrypt(b, dict(h))

    def test_pn_handling_late_delivery(self):
        """Alice sends 3; Bob reads 1; Bob replies; late delivery of 2,3 still works."""
        alice_x, bob_x = self._pair()
        a = init_alice(alice_x.private_bytes_raw(), bob_x.public_key().public_bytes_raw())
        chain1 = [ratchet_encrypt(a, b"c%d" % i) for i in range(3)]
        b = init_bob(
            bob_x.private_bytes_raw(),
            alice_x.public_key().public_bytes_raw(),
            base64.b64decode(chain1[0][0]["dh"]),
        )
        assert ratchet_decrypt(b, dict(chain1[0][0])) == chain1[0][1]

        # Bob replies before reading chain1[1] and chain1[2].
        hr, mkr = ratchet_encrypt(b, b"reply")
        assert ratchet_decrypt(a, dict(hr)) == mkr

        later = [ratchet_encrypt(a, b"d%d" % i) for i in range(2)]
        assert ratchet_decrypt(b, dict(later[0][0])) == later[0][1]
        assert ratchet_decrypt(b, dict(later[1][0])) == later[1][1]
        # Late delivery of the first chain's unread messages.
        assert ratchet_decrypt(b, dict(chain1[1][0])) == chain1[1][1]
        assert ratchet_decrypt(b, dict(chain1[2][0])) == chain1[2][1]

    def test_max_skip_rejected(self):
        alice_x, bob_x = self._pair()
        a = init_alice(alice_x.private_bytes_raw(), bob_x.public_key().public_bytes_raw())
        header, _ = ratchet_encrypt(a, b"m0")
        b = init_bob(
            bob_x.private_bytes_raw(),
            alice_x.public_key().public_bytes_raw(),
            base64.b64decode(header["dh"]),
        )
        too_far = dict(header)
        too_far["n"] = MAX_SKIP + 5
        with pytest.raises(TooFarAheadError):
            ratchet_decrypt(b, too_far)


class TestRatchetFacade:
    """End-to-end facade behaviour over the transport contract."""

    def _identities(self):
        a_ed, _ = KeyGenerator.generate_identity_keypair()
        b_ed, _ = KeyGenerator.generate_identity_keypair()
        a_x, b_x = _x25519(), _x25519()
        return a_ed, b_ed, a_x, b_x

    def _setup(self):
        a_ed, b_ed, a_x, b_x = self._identities()
        a_store = _make_store(a_x, "alice")
        b_store = _make_store(b_x, "bob")
        return a_ed, b_ed, a_x, b_x, a_store, b_store

    def test_roundtrip_and_own_copy(self):
        a_ed, b_ed, a_x, b_x, a_store, b_store = self._setup()
        enc, dec = RatchetEncryptor(), RatchetDecryptor()
        data = enc.encrypt_message(
            "hello bob",
            peer_key="bob",
            peer_identity_x25519_pub=b_x.public_key(),
            sender_ed25519_priv=a_ed,
            sender_x25519_priv=a_x,
            sender_id="1",
            recipient_id="2",
            store=a_store,
        )
        assert peek_blob_version(data["blob"]) == 2
        assert _decrypt(dec, data, "alice", b_x, a_ed.public_key(), a_x.public_key(), b_store) == "hello bob"
        # Sender's own copy is stateless and uses the v1 path.
        assert MessageDecryptor().decrypt_own_message(data["sender_blob"], a_x) == "hello bob"

    def test_bidirectional_conversation(self):
        a_ed, b_ed, a_x, b_x, a_store, b_store = self._setup()
        enc, dec = RatchetEncryptor(), RatchetDecryptor()
        d1 = enc.encrypt_message(
            "hi", peer_key="bob", peer_identity_x25519_pub=b_x.public_key(),
            sender_ed25519_priv=a_ed, sender_x25519_priv=a_x,
            sender_id="1", recipient_id="2", store=a_store)
        assert _decrypt(dec, d1, "alice", b_x, a_ed.public_key(), a_x.public_key(), b_store) == "hi"
        d2 = enc.encrypt_message(
            "yo", peer_key="alice", peer_identity_x25519_pub=a_x.public_key(),
            sender_ed25519_priv=b_ed, sender_x25519_priv=b_x,
            sender_id="2", recipient_id="1", store=b_store)
        assert _decrypt(dec, d2, "bob", a_x, b_ed.public_key(), b_x.public_key(), a_store) == "yo"

    def test_legacy_v1_still_decrypts_and_routes(self):
        a_ed, b_ed, a_x, b_x, a_store, b_store = self._setup()
        v1 = MessageEncryptor().encrypt_message(
            "legacy", b_x.public_key(), a_ed, a_x.public_key(), "1", "2")
        assert peek_blob_version(v1["blob"]) == 1
        assert (
            MessageDecryptor().decrypt_message(
                {"blob": v1["blob"], "signature": v1["signature"]},
                b_x,
                a_ed.public_key(),
            )
            == "legacy"
        )

    def test_signature_verified_before_state(self):
        a_ed, b_ed, a_x, b_x, a_store, b_store = self._setup()
        enc, dec = RatchetEncryptor(), RatchetDecryptor()
        d1 = enc.encrypt_message(
            "one", peer_key="bob", peer_identity_x25519_pub=b_x.public_key(),
            sender_ed25519_priv=a_ed, sender_x25519_priv=a_x,
            sender_id="1", recipient_id="2", store=a_store)
        _decrypt(dec, d1, "alice", b_x, a_ed.public_key(), a_x.public_key(), b_store)
        before = copy.deepcopy(b_store.get("alice"))

        d2 = enc.encrypt_message(
            "two", peer_key="bob", peer_identity_x25519_pub=b_x.public_key(),
            sender_ed25519_priv=a_ed, sender_x25519_priv=a_x,
            sender_id="1", recipient_id="2", store=a_store)
        # Corrupt the signature; verification must fail before any state change.
        sig = bytearray(base64.b64decode(d2["signature"]))
        sig[0] ^= 0xFF
        tampered = {"blob": d2["blob"], "signature": base64.b64encode(bytes(sig)).decode()}
        with pytest.raises(InvalidSignature):
            dec.decrypt_message(
                tampered, peer_key="alice", recipient_x25519_priv=b_x,
                sender_ed25519_pub=a_ed.public_key(), sender_x25519_pub=a_x.public_key(),
                store=b_store)
        after = b_store.get("alice")
        assert after.root_key == before.root_key
        assert after.n_r == before.n_r

    def test_simultaneous_init_converges(self):
        a_ed, b_ed, a_x, b_x, a_store, b_store = self._setup()
        enc, dec = RatchetEncryptor(), RatchetDecryptor()
        # Both send a first message before either receives.
        da = enc.encrypt_message(
            "A1", peer_key="bob", peer_identity_x25519_pub=b_x.public_key(),
            sender_ed25519_priv=a_ed, sender_x25519_priv=a_x,
            sender_id="1", recipient_id="2", store=a_store)
        db = enc.encrypt_message(
            "B1", peer_key="alice", peer_identity_x25519_pub=a_x.public_key(),
            sender_ed25519_priv=b_ed, sender_x25519_priv=b_x,
            sender_id="2", recipient_id="1", store=b_store)
        assert _decrypt(dec, da, "alice", b_x, a_ed.public_key(), a_x.public_key(), b_store) == "A1"
        assert _decrypt(dec, db, "bob", a_x, b_ed.public_key(), b_x.public_key(), a_store) == "B1"
        # Subsequent exchange must converge (at most a transient drop).
        recovered = 0
        for i, sender in enumerate(["A", "B", "A", "B"]):
            if sender == "A":
                d = enc.encrypt_message(
                    "x%d" % i, peer_key="bob", peer_identity_x25519_pub=b_x.public_key(),
                    sender_ed25519_priv=a_ed, sender_x25519_priv=a_x,
                    sender_id="1", recipient_id="2", store=a_store)
                try:
                    _decrypt(dec, d, "alice", b_x, a_ed.public_key(), a_x.public_key(), b_store)
                    recovered += 1
                except InvalidTag:
                    pass
            else:
                d = enc.encrypt_message(
                    "y%d" % i, peer_key="alice", peer_identity_x25519_pub=a_x.public_key(),
                    sender_ed25519_priv=b_ed, sender_x25519_priv=b_x,
                    sender_id="2", recipient_id="1", store=b_store)
                try:
                    _decrypt(dec, d, "bob", a_x, b_ed.public_key(), b_x.public_key(), a_store)
                    recovered += 1
                except InvalidTag:
                    pass
        assert recovered >= 3  # converges after at most one dropped message

    def test_peer_state_loss_heals(self):
        a_ed, b_ed, a_x, b_x, a_store, b_store = self._setup()
        enc, dec = RatchetEncryptor(), RatchetDecryptor()
        d1 = enc.encrypt_message(
            "m1", peer_key="bob", peer_identity_x25519_pub=b_x.public_key(),
            sender_ed25519_priv=a_ed, sender_x25519_priv=a_x,
            sender_id="1", recipient_id="2", store=a_store)
        _decrypt(dec, d1, "alice", b_x, a_ed.public_key(), a_x.public_key(), b_store)
        b_store.delete("alice")
        d2 = enc.encrypt_message(
            "m2", peer_key="bob", peer_identity_x25519_pub=b_x.public_key(),
            sender_ed25519_priv=a_ed, sender_x25519_priv=a_x,
            sender_id="1", recipient_id="2", store=a_store)
        assert _decrypt(dec, d2, "alice", b_x, a_ed.public_key(), a_x.public_key(), b_store) == "m2"


class TestPersistence:
    """At-rest persistence of ratchet sessions and plaintext bodies."""

    def test_session_survives_reload(self):
        a_x, b_x = _x25519(), _x25519()
        backing = _MemStorage()
        st = init_alice(a_x.private_bytes_raw(), b_x.public_key().public_bytes_raw())
        RatchetSessionStore(backing, a_x.private_bytes_raw(), "alice").put("bob", st)
        reloaded = RatchetSessionStore(backing, a_x.private_bytes_raw(), "alice")
        got = reloaded.get("bob")
        assert got is not None
        assert got.root_key == st.root_key

    def test_session_wrong_key_yields_empty(self):
        a_x, b_x = _x25519(), _x25519()
        backing = _MemStorage()
        st = init_alice(a_x.private_bytes_raw(), b_x.public_key().public_bytes_raw())
        RatchetSessionStore(backing, a_x.private_bytes_raw(), "alice").put("bob", st)
        other = RatchetSessionStore(backing, _x25519().private_bytes_raw(), "alice")
        assert other.get("bob") is None

    def test_plaintext_store_roundtrip(self):
        a_x = _x25519()
        backing = _MemStorage()
        PlaintextMessageStore(backing, a_x.private_bytes_raw(), "alice").put(42, "hello")
        reloaded = PlaintextMessageStore(backing, a_x.private_bytes_raw(), "alice")
        assert reloaded.get(42) == "hello"
        assert reloaded.get(99) is None

    def test_continue_conversation_across_reload(self):
        a_ed, _ = KeyGenerator.generate_identity_keypair()
        b_ed, _ = KeyGenerator.generate_identity_keypair()
        a_x, b_x = _x25519(), _x25519()
        a_backing, b_backing = _MemStorage(), _MemStorage()
        enc, dec = RatchetEncryptor(), RatchetDecryptor()

        a_store = RatchetSessionStore(a_backing, a_x.private_bytes_raw(), "alice")
        b_store = RatchetSessionStore(b_backing, b_x.private_bytes_raw(), "bob")
        d1 = enc.encrypt_message(
            "before", peer_key="bob", peer_identity_x25519_pub=b_x.public_key(),
            sender_ed25519_priv=a_ed, sender_x25519_priv=a_x,
            sender_id="1", recipient_id="2", store=a_store)
        _decrypt(dec, d1, "alice", b_x, a_ed.public_key(), a_x.public_key(), b_store)

        # Simulate restart: rebuild stores from the same backing storage.
        a_store2 = RatchetSessionStore(a_backing, a_x.private_bytes_raw(), "alice")
        b_store2 = RatchetSessionStore(b_backing, b_x.private_bytes_raw(), "bob")
        d2 = enc.encrypt_message(
            "after", peer_key="bob", peer_identity_x25519_pub=b_x.public_key(),
            sender_ed25519_priv=a_ed, sender_x25519_priv=a_x,
            sender_id="1", recipient_id="2", store=a_store2)
        assert _decrypt(dec, d2, "alice", b_x, a_ed.public_key(), a_x.public_key(), b_store2) == "after"
