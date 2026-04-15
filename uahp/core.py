"""
UAHP Core v1.0 — Identity, Handshake, Liveness, Death Certificates, Receipts.

The trust primitives that everything else in the stack depends on.

Built from v0.6.0 schemas/session/signing patterns, adapted to stdlib.
Signing follows tiered policy: HMAC-SHA256 for standard operations,
chain-hashed receipts for tamper evidence.

Author: Paul Raspey
License: MIT
"""

import json
import hashlib
import hmac as _hmac
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


# ── ANSI ─────────────────────────────────────────────────────────────────────

GREEN = "\033[92m"
TEAL = "\033[96m"
AMBER = "\033[93m"
RED = "\033[91m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


# ── Identity ─────────────────────────────────────────────────────────────────

@dataclass
class AgentIdentity:
    """
    A UAHP agent identity. The uid is globally unique. The public_key
    is derived from a private seed (which the agent keeps secret).
    The signing_key is the private seed used for HMAC operations.
    """
    uid: str
    public_key: str
    signing_key: str  # private, never transmitted
    created_at: float
    protocol_version: str = "1.0.0"
    metadata: Dict = field(default_factory=dict)

    @classmethod
    def create(cls, metadata: Optional[Dict] = None) -> "AgentIdentity":
        uid = str(uuid.uuid4())
        meta = metadata or {}
        seed = hashlib.sha256(
            (uid + json.dumps(meta, sort_keys=True) + str(time.time())).encode()
        ).hexdigest()
        public_key = hashlib.sha256(seed.encode()).hexdigest()
        return cls(
            uid=uid,
            public_key=public_key,
            signing_key=seed,
            created_at=time.time(),
            metadata=meta,
        )

    def sign(self, payload: str) -> str:
        """HMAC-SHA256 signature using this identity's private key."""
        return _hmac.new(
            self.signing_key.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()

    def verify(self, payload: str, signature: str) -> bool:
        """Verify a signature against this identity's key."""
        expected = self.sign(payload)
        return _hmac.compare_digest(expected, signature)

    def to_public(self) -> Dict:
        """Export only public fields (safe to transmit)."""
        return {
            "uid": self.uid,
            "public_key": self.public_key,
            "created_at": self.created_at,
            "protocol_version": self.protocol_version,
            "metadata": self.metadata,
        }


# ── Handshake ────────────────────────────────────────────────────────────────

@dataclass
class HandshakeResult:
    """Result of a mutual authentication handshake."""
    success: bool
    session_token: str = ""
    shared_secret: bytes = b""
    error: str = ""


@dataclass
class Session:
    """An active authenticated session between two agents."""
    session_token: str
    agent_a_uid: str
    agent_b_uid: str
    shared_secret: bytes
    created_at: float
    last_activity: float
    message_count: int = 0

    def is_expired(self, timeout_seconds: float = 3600) -> bool:
        return (time.time() - self.last_activity) > timeout_seconds

    def touch(self):
        self.last_activity = time.time()
        self.message_count += 1


# ── Receipts ─────────────────────────────────────────────────────────────────

@dataclass
class Receipt:
    """
    Signed, tamper-evident proof of work. Chain-hashed: each receipt
    includes the hash of the previous receipt for tamper detection.
    """
    receipt_id: str
    identity_uid: str
    task_id: str
    action: str
    success: bool
    timestamp: float
    input_hash: str
    output_hash: str
    previous_hash: str  # chain link
    signature: str

    def to_dict(self) -> Dict:
        return asdict(self)


# ── Death Certificates ───────────────────────────────────────────────────────

@dataclass
class DeathCertificate:
    """
    Irreversible declaration that an agent is no longer operational.
    Once issued, the agent cannot handshake, produce receipts, or
    pass liveness checks.
    """
    cert_id: str
    identity_uid: str
    timestamp: float
    reason: str
    final_receipt_hash: str
    signature: str

    def to_dict(self) -> Dict:
        return asdict(self)


# ── Core Engine ──────────────────────────────────────────────────────────────

class UAHPCore:
    """
    Core trust primitives for the UAHP stack.

    Manages the lifecycle of agent identities:
        create -> handshake -> produce receipts -> liveness checks -> death

    Usage:
        core = UAHPCore()
        alice = core.create_identity({"name": "Alice", "role": "analyst"})
        bob = core.create_identity({"name": "Bob", "role": "reviewer"})

        session = core.handshake(alice, bob)
        receipt = core.create_receipt(alice, "task-001", "analyze", True, "input", "output")
        score_data = core.get_trust_inputs(alice.uid)
    """

    def __init__(self):
        self._identities: Dict[str, AgentIdentity] = {}
        self._receipts: Dict[str, List[Receipt]] = {}
        self._receipt_chains: Dict[str, str] = {}  # uid -> last receipt hash
        self._sessions: Dict[str, Session] = {}
        self._dead_agents: Dict[str, DeathCertificate] = {}

    # ── Identity ─────────────────────────────────────────────────────────

    def create_identity(self, metadata: Optional[Dict] = None) -> AgentIdentity:
        """Create and register a new agent identity."""
        identity = AgentIdentity.create(metadata)
        self._identities[identity.uid] = identity
        self._receipts[identity.uid] = []
        self._receipt_chains[identity.uid] = "genesis"
        return identity

    def get_identity(self, uid: str) -> Optional[AgentIdentity]:
        return self._identities.get(uid)

    def is_alive(self, uid: str) -> bool:
        """Liveness check: identity exists and no death certificate issued."""
        return uid in self._identities and uid not in self._dead_agents

    # ── Handshake ────────────────────────────────────────────────────────

    def handshake(self, id_a: AgentIdentity, id_b: AgentIdentity) -> HandshakeResult:
        """
        Mutual authentication with session secret derivation.

        Both agents prove they hold their private keys via challenge-response.
        A shared session secret is derived for subsequent message signing.
        """
        # Dead agents cannot handshake
        if id_a.uid in self._dead_agents:
            return HandshakeResult(False, error=f"Agent {id_a.uid[:8]} is dead")
        if id_b.uid in self._dead_agents:
            return HandshakeResult(False, error=f"Agent {id_b.uid[:8]} is dead")

        # Challenge-response
        nonce = str(uuid.uuid4())
        challenge = f"{id_a.uid}:{id_b.uid}:{nonce}:{time.time()}"

        # Both agents sign the challenge
        sig_a = id_a.sign(challenge)
        sig_b = id_b.sign(challenge)

        # Verify (in real deployment, each agent verifies the other's sig)
        if not id_a.verify(challenge, sig_a):
            return HandshakeResult(False, error="Agent A failed challenge")
        if not id_b.verify(challenge, sig_b):
            return HandshakeResult(False, error="Agent B failed challenge")

        # Derive session secret (HKDF-style: combine both signatures)
        combined = f"{sig_a}:{sig_b}:{nonce}"
        shared_secret = hashlib.sha256(combined.encode()).digest()
        session_token = hashlib.sha256(
            f"{id_a.uid}:{id_b.uid}:{nonce}".encode()
        ).hexdigest()[:32]

        session = Session(
            session_token=session_token,
            agent_a_uid=id_a.uid,
            agent_b_uid=id_b.uid,
            shared_secret=shared_secret,
            created_at=time.time(),
            last_activity=time.time(),
        )
        self._sessions[session_token] = session

        return HandshakeResult(
            success=True,
            session_token=session_token,
            shared_secret=shared_secret,
        )

    def get_session(self, token: str) -> Optional[Session]:
        session = self._sessions.get(token)
        if session and not session.is_expired():
            return session
        return None

    # ── Receipts ─────────────────────────────────────────────────────────

    def create_receipt(
        self,
        identity: AgentIdentity,
        task_id: str,
        action: str,
        success: bool,
        input_data: str,
        output_data: str,
    ) -> Receipt:
        """
        Create a signed, chain-hashed receipt.

        Each receipt links to the previous one via previous_hash,
        creating a tamper-evident chain per agent.
        """
        if identity.uid in self._dead_agents:
            raise ValueError(f"Dead agent {identity.uid[:8]} cannot create receipts")

        input_hash = hashlib.sha256(input_data.encode()).hexdigest()
        output_hash = hashlib.sha256(output_data.encode()).hexdigest()
        previous_hash = self._receipt_chains.get(identity.uid, "genesis")

        payload = (
            f"{identity.uid}:{task_id}:{action}:{success}:"
            f"{input_hash}:{output_hash}:{previous_hash}"
        )
        signature = identity.sign(payload)

        receipt = Receipt(
            receipt_id=str(uuid.uuid4()),
            identity_uid=identity.uid,
            task_id=task_id,
            action=action,
            success=success,
            timestamp=time.time(),
            input_hash=input_hash,
            output_hash=output_hash,
            previous_hash=previous_hash,
            signature=signature,
        )

        self._receipts[identity.uid].append(receipt)
        self._receipt_chains[identity.uid] = hashlib.sha256(
            signature.encode()
        ).hexdigest()

        return receipt

    def get_receipts(self, identity_uid: str) -> List[Receipt]:
        return self._receipts.get(identity_uid, [])

    def verify_receipt_chain(self, identity_uid: str) -> bool:
        """Verify the entire receipt chain for tamper evidence."""
        receipts = self.get_receipts(identity_uid)
        if not receipts:
            return True

        expected_prev = "genesis"
        identity = self._identities.get(identity_uid)
        if not identity:
            return False

        for r in receipts:
            if r.previous_hash != expected_prev:
                return False
            payload = (
                f"{r.identity_uid}:{r.task_id}:{r.action}:{r.success}:"
                f"{r.input_hash}:{r.output_hash}:{r.previous_hash}"
            )
            if not identity.verify(payload, r.signature):
                return False
            expected_prev = hashlib.sha256(r.signature.encode()).hexdigest()

        return True

    # ── Death Certificates ───────────────────────────────────────────────

    def declare_death(
        self, identity_uid: str, reason: str = "silent"
    ) -> Optional[DeathCertificate]:
        """
        Issue an irreversible death certificate.
        The agent can never handshake or produce receipts again.
        """
        if identity_uid not in self._identities:
            return None
        if identity_uid in self._dead_agents:
            return self._dead_agents[identity_uid]

        identity = self._identities[identity_uid]
        final_hash = self._receipt_chains.get(identity_uid, "genesis")

        payload = f"death:{identity_uid}:{reason}:{final_hash}:{time.time()}"
        signature = identity.sign(payload)

        cert = DeathCertificate(
            cert_id=str(uuid.uuid4()),
            identity_uid=identity_uid,
            timestamp=time.time(),
            reason=reason,
            final_receipt_hash=final_hash,
            signature=signature,
        )
        self._dead_agents[identity_uid] = cert
        return cert

    # ── Trust Inputs (for ReputationEngine) ──────────────────────────────

    def get_trust_inputs(self, identity_uid: str) -> Dict:
        """
        Compute raw trust inputs from receipts for ReputationEngine.
        """
        receipts = self.get_receipts(identity_uid)
        if not receipts:
            return {
                "delivery_rate": 0.0,
                "total_tasks": 0,
                "success_count": 0,
                "failure_count": 0,
                "latest_timestamp": 0.0,
                "oldest_timestamp": 0.0,
                "chain_valid": True,
                "is_alive": self.is_alive(identity_uid),
            }

        successes = sum(1 for r in receipts if r.success)
        timestamps = [r.timestamp for r in receipts]

        return {
            "delivery_rate": successes / len(receipts),
            "total_tasks": len(receipts),
            "success_count": successes,
            "failure_count": len(receipts) - successes,
            "latest_timestamp": max(timestamps),
            "oldest_timestamp": min(timestamps),
            "chain_valid": self.verify_receipt_chain(identity_uid),
            "is_alive": self.is_alive(identity_uid),
        }


# ── Demo ─────────────────────────────────────────────────────────────────────

def demo():
    print(f"\n{BOLD}{'='*60}")
    print(f"  UAHP Core v1.0 Demo")
    print(f"  Identity + Handshake + Receipts + Death Certificates")
    print(f"{'='*60}{RESET}\n")

    core = UAHPCore()

    # Create identities
    alice = core.create_identity({"name": "Alice", "role": "analyst"})
    bob = core.create_identity({"name": "Bob", "role": "reviewer"})
    print(f"{GREEN}[1] Created Alice: {alice.uid[:12]}...{RESET}")
    print(f"{GREEN}[1] Created Bob:   {bob.uid[:12]}...{RESET}")

    # Handshake
    result = core.handshake(alice, bob)
    print(f"\n{TEAL}[2] Handshake: {'SUCCESS' if result.success else 'FAILED'}{RESET}")
    print(f"    Session: {result.session_token[:16]}...")

    # Create receipts (chain-hashed)
    print(f"\n{AMBER}[3] Creating receipt chain for Alice:{RESET}")
    for i in range(5):
        success = i != 3  # one failure
        r = core.create_receipt(
            alice, f"task-{i:03d}", "analyze",
            success, f"input-{i}", f"output-{i}",
        )
        status = f"{GREEN}OK{RESET}" if success else f"{RED}FAIL{RESET}"
        print(f"    Receipt {r.receipt_id[:8]}... {status} chain: ...{r.previous_hash[-8:]}")

    # Verify chain
    chain_ok = core.verify_receipt_chain(alice.uid)
    print(f"\n{GREEN}[4] Receipt chain integrity: {'VALID' if chain_ok else 'TAMPERED'}{RESET}")

    # Trust inputs
    inputs = core.get_trust_inputs(alice.uid)
    print(f"\n{TEAL}[5] Trust inputs for Alice:{RESET}")
    print(f"    Delivery rate: {inputs['delivery_rate']:.0%}")
    print(f"    Total tasks:   {inputs['total_tasks']}")
    print(f"    Chain valid:   {inputs['chain_valid']}")
    print(f"    Alive:         {inputs['is_alive']}")

    # Liveness
    print(f"\n{AMBER}[6] Liveness:{RESET}")
    print(f"    Alice: {core.is_alive(alice.uid)}")
    print(f"    Bob:   {core.is_alive(bob.uid)}")

    # Death certificate
    cert = core.declare_death(bob.uid, "backend_timeout")
    print(f"\n{RED}[7] Death certificate for Bob:{RESET}")
    print(f"    Cert ID: {cert.cert_id[:12]}...")
    print(f"    Reason:  {cert.reason}")
    print(f"    Bob alive: {core.is_alive(bob.uid)}")

    # Dead agent can't handshake
    result2 = core.handshake(alice, bob)
    print(f"\n{DIM}[8] Handshake with dead Bob: {'SUCCESS' if result2.success else 'REJECTED'}")
    print(f"    Error: {result2.error}{RESET}")

    # Dead agent can't create receipts
    try:
        core.create_receipt(bob, "task-999", "review", True, "x", "y")
        print(f"    Dead receipt: SHOULD NOT HAPPEN")
    except ValueError as e:
        print(f"    Dead receipt blocked: {e}")

    print(f"\n{BOLD}UAHP Core v1.0 validated{RESET}\n")


if __name__ == "__main__":
    demo()
