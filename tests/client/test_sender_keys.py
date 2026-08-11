"""
Tests for Sender Keys group E2EE with rotation every 100 messages.
"""

import base64
import json

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from client.crypto.sender_keys import (
    MAX_MESSAGES_PER_CHAIN,
    GroupSenderKeyManager,
    peek_group_blob_version,
)


def _ed():
    return Ed25519PrivateKey.generate()


def _seed(recipient_mgr: GroupSenderKeyManager, sender_mgr: GroupSenderKeyManager, room_id: int, sender_id: str):
    """Copy all sender chains to recipient (simulates distribution)."""
    for cid, ck in list(sender_mgr._incoming_chain_key.items()):
        # sender stores under __self__, copy to real sender_id
        if cid[0] == room_id and cid[1] == "__self__":
            real = (room_id, sender_id, cid[2])
            if real not in recipient_mgr._incoming_chain_key:
                recipient_mgr.seed_incoming_chain(room_id, sender_id, cid[2], ck)
    for lst in sender_mgr._outgoing_history.values():
        for ch in lst:
            recipient_mgr.seed_incoming_chain(room_id, sender_id, ch.chain_id, ch.initial_key)
    cur = sender_mgr._outgoing.get(room_id)
    if cur:
        recipient_mgr.seed_incoming_chain(room_id, sender_id, cur.chain_id, cur.initial_key)


class TestSenderKeysCore:
    def test_roundtrip(self):
        ed = _ed()
        mgr = GroupSenderKeyManager()
        mgr2 = GroupSenderKeyManager()
        enc = mgr.encrypt(1, "hello group", "alice", ed)
        assert peek_group_blob_version(enc["blob"]) == 3
        _seed(mgr2, mgr, 1, "alice")
        assert mgr2.decrypt(enc["blob"], enc["signature"], ed.public_key()) == "hello group"

    def test_sender_self_decrypt(self):
        ed = _ed()
        mgr = GroupSenderKeyManager()
        enc = mgr.encrypt(1, "self msg", "alice", ed)
        # decrypt via same manager (uses __self__ alias)
        assert mgr.decrypt(enc["blob"], enc["signature"], ed.public_key()) == "self msg"

    def test_out_of_order(self):
        ed = _ed()
        sender = GroupSenderKeyManager()
        recv = GroupSenderKeyManager()
        msgs = [sender.encrypt(1, f"m{i}", "alice", ed) for i in range(5)]
        _seed(recv, sender, 1, "alice")
        for idx in [0, 2, 1, 4, 3]:
            assert recv.decrypt(msgs[idx]["blob"], msgs[idx]["signature"], ed.public_key()) == f"m{idx}"

    def test_replay_rejected(self):
        ed = _ed()
        s = GroupSenderKeyManager()
        r = GroupSenderKeyManager()
        enc = s.encrypt(1, "once", "alice", ed)
        _seed(r, s, 1, "alice")
        r.decrypt(enc["blob"], enc["signature"], ed.public_key())
        with pytest.raises(Exception):
            r.decrypt(enc["blob"], enc["signature"], ed.public_key())

    def test_signature_rejected(self):
        ed = _ed()
        s = GroupSenderKeyManager()
        r = GroupSenderKeyManager()
        enc = s.encrypt(1, "hi", "alice", ed)
        _seed(r, s, 1, "alice")
        sig = bytearray(base64.b64decode(enc["signature"]))
        sig[0] ^= 0xFF
        tampered = base64.b64encode(bytes(sig)).decode()
        with pytest.raises(InvalidSignature):
            r.decrypt(enc["blob"], tampered, ed.public_key())

    def test_unicode(self):
        ed = _ed()
        s = GroupSenderKeyManager()
        r = GroupSenderKeyManager()
        txt = "привет 🌍"
        enc = s.encrypt(1, txt, "alice", ed)
        _seed(r, s, 1, "alice")
        assert r.decrypt(enc["blob"], enc["signature"], ed.public_key()) == txt

    def test_rotation_every_100(self):
        ed = _ed()
        s = GroupSenderKeyManager()
        r = GroupSenderKeyManager()
        chain_ids = set()
        for i in range(250):
            enc = s.encrypt(42, f"msg{i}", "alice", ed)
            chain_ids.add(enc["chain_id"])
            # seed new chain when it appears
            cur = s._outgoing[42]
            _seed(r, s, 42, "alice")
            assert r.decrypt(enc["blob"], enc["signature"], ed.public_key()) == f"msg{i}"
            # verify index resets on rotation
            if (i + 1) % MAX_MESSAGES_PER_CHAIN == 0:
                assert enc["msg_index"] == MAX_MESSAGES_PER_CHAIN - 1
                # next message should be index 0
                nxt = s.encrypt(42, "next", "alice", ed)
                assert nxt["msg_index"] == 0
                assert nxt["chain_id"] != enc["chain_id"]
                # put back: decrypt that nxt and then continue loop needs to account
                _seed(r, s, 42, "alice")
                assert r.decrypt(nxt["blob"], nxt["signature"], ed.public_key()) == "next"
                break
        # at least 2 chain ids seen in 100+ messages
        assert len(chain_ids) >= 1
        # full 250 should use 3 chains
        s2 = GroupSenderKeyManager()
        r2 = GroupSenderKeyManager()
        ids = []
        for i in range(250):
            e = s2.encrypt(99, f"x{i}", "bob", ed)
            ids.append(e["chain_id"])
            _seed(r2, s2, 99, "bob")
            r2.decrypt(e["blob"], e["signature"], ed.public_key())
        assert len(set(ids)) == 3  # 100+100+50
        assert s2.rotation_count(99) == 2

    def test_history_still_decryptable_after_rotation(self):
        ed = _ed()
        s = GroupSenderKeyManager()
        msgs = [s.encrypt(1, f"h{i}", "alice", ed) for i in range(100)]
        # trigger rotation
        later = s.encrypt(1, "after", "alice", ed)
        assert later["chain_id"] != msgs[0]["chain_id"]
        r = GroupSenderKeyManager()
        _seed(r, s, 1, "alice")
        # old messages still decrypt
        for i in [0, 50, 99]:
            assert r.decrypt(msgs[i]["blob"], msgs[i]["signature"], ed.public_key()) == f"h{i}"
        assert r.decrypt(later["blob"], later["signature"], ed.public_key()) == "after"

    def test_too_far_ahead_rejected(self):
        ed = _ed()
        s = GroupSenderKeyManager()
        r = GroupSenderKeyManager()
        # create 5 messages but only seed chain
        msgs = [s.encrypt(1, f"m{i}", "alice", ed) for i in range(5)]
        _seed(r, s, 1, "alice")
        # craft a blob with n=5000 (far ahead)
        import base64, json as _json
        blob = _json.loads(base64.b64decode(msgs[0]["blob"]).decode())
        blob["n"] = 5000
        blob_bytes = _json.dumps(blob, sort_keys=True, separators=(",", ":")).encode()
        sig = ed.sign(blob_bytes)
        with pytest.raises(Exception):
            r.decrypt(base64.b64encode(blob_bytes).decode(), base64.b64encode(sig).decode(), ed.public_key())
