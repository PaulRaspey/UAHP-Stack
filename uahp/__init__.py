"""UAHP Stack v1.0 — Trust infrastructure for autonomous agents."""
from .core import UAHPCore, AgentIdentity, Receipt, DeathCertificate, HandshakeResult
from .reputation import ReputationEngine, TrustProfile
from .compliance import ComplianceEngine, ComplianceReport

__version__ = "1.0.0"
__author__ = "Paul Raspey"
