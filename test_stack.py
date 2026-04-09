"""
UAHP Stack Integration Test
============================
Exercises the full pipeline: identity -> handshake -> work -> receipts
-> reputation -> compliance -> A2A card generation.

Run: python -m pytest tests/ or python tests/test_stack.py
"""

import sys
import os
import time
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import UAHPCore, AgentIdentity, AgentStatus, CompletionReceipt
from reputation import ReputationEngine, TrustProfile
from compliance import ComplianceEngine, RiskLevel
from a2a import A2AIntegration, A2AAgentCard


def test_full_stack():
    """Integration test: full lifecycle of two agents interacting."""
    print("UAHP Stack Integration Test")
    print("=" * 60)

    # 1. Initialize core
    uahp = UAHPCore()
    reputation = ReputationEngine(uahp)
    compliance = ComplianceEngine(uahp)
    a2a = A2AIntegration(uahp, reputation)

    # 2. Create agent identities
    print("\n[1] Creating identities...")
    alice = uahp.create_identity({"name": "Alice", "description": "Data analyst agent"})
    bob = uahp.create_identity({"name": "Bob", "description": "Code review agent"})
    print(f"  Alice: {alice.agent_id}")
    print(f"  Bob:   {bob.agent_id}")

    # 3. Mutual authentication handshake
    print("\n[2] Handshake...")
    result = uahp.handshake(alice, bob)
    assert result.success, "Handshake failed"
    print(f"  Success: {result.success}")
    print(f"  Session: {result.session_token[:16]}...")

    # 4. Liveness checks
    print("\n[3] Liveness checks...")
    alice_live = uahp.liveness_check(alice)
    bob_live = uahp.liveness_check(bob)
    assert alice_live.valid, "Alice liveness failed"
    assert bob_live.valid, "Bob liveness failed"
    print(f"  Alice alive: {alice_live.valid}")
    print(f"  Bob alive:   {bob_live.valid}")

    # 5. Generate completion receipts (simulate work)
    print("\n[4] Simulating work (generating receipts)...")
    tasks = [
        ("task-001", "analyze_dataset", 1200, True),
        ("task-002", "generate_report", 3400, True),
        ("task-003", "validate_schema", 800, True),
        ("task-004", "run_pipeline", 15000, False),  # one failure
        ("task-005", "summarize_results", 2100, True),
        ("task-006", "archive_output", 450, True),
        ("task-007", "notify_stakeholders", 300, True),
    ]

    for task_id, action, dur, success in tasks:
        receipt = uahp.create_receipt(
            identity=alice,
            task_id=task_id,
            action=action,
            duration_ms=dur,
            success=success,
            input_data=f"input for {task_id}",
            output_data=f"output for {task_id}",
        )

    # Bob does fewer tasks
    for task_id, action, dur, success in tasks[:3]:
        uahp.create_receipt(
            identity=bob,
            task_id=f"bob-{task_id}",
            action=action,
            duration_ms=dur * 1.2,
            success=success,
            input_data=f"bob input for {task_id}",
            output_data=f"bob output for {task_id}",
        )

    alice_receipts = uahp.get_receipts(alice.agent_id)
    bob_receipts = uahp.get_receipts(bob.agent_id)
    print(f"  Alice receipts: {len(alice_receipts)}")
    print(f"  Bob receipts:   {len(bob_receipts)}")

    # 6. Reputation scoring
    print("\n[5] Trust scores...")
    alice_trust = reputation.score_agent(alice.agent_id)
    bob_trust = reputation.score_agent(bob.agent_id)
    print(f"  Alice: {alice_trust.trust_score:.4f} ({ReputationEngine.trust_label(alice_trust.trust_score)})")
    print(f"  Bob:   {bob_trust.trust_score:.4f} ({ReputationEngine.trust_label(bob_trust.trust_score)})")
    print(f"  Alice delivery rate: {alice_trust.delivery_rate:.2%}")
    print(f"  Bob delivery rate:   {bob_trust.delivery_rate:.2%}")

    # 7. Receipt verification
    print("\n[6] Receipt verification...")
    verified = uahp.verify_receipt(alice_receipts[0], alice)
    tampered = uahp.verify_receipt(alice_receipts[0], bob)  # wrong agent
    print(f"  Correct agent: {verified}")
    print(f"  Wrong agent:   {tampered}")
    assert verified, "Valid receipt failed verification"
    assert not tampered, "Tampered receipt passed verification"

    # 8. EU AI Act compliance report
    print("\n[7] Compliance report (EU AI Act)...")
    report = compliance.generate_report(alice.agent_id, alice_receipts, RiskLevel.LIMITED)
    print(f"  Report ID:     {report.report_id}")
    print(f"  Risk level:    {report.risk_level}")
    print(f"  Total actions: {report.total_actions}")
    print(f"  Delivery rate: {report.delivery_rate:.2%}")
    print(f"  Chain hash:    {report.chain_hash[:24]}...")
    print(f"  Audit entries: {len(report.audit_entries)}")

    # 9. A2A Agent Card generation
    print("\n[8] A2A Agent Card...")
    card = a2a.generate_agent_card(
        identity=alice,
        name="Alice",
        description="Data analyst agent",
        url="https://agents.example.com/alice",
        skills=[{"name": "data_analysis"}, {"name": "reporting"}],
    )
    print(f"  Name:        {card.name}")
    print(f"  Trust score: {card.uahp_trust_score}")
    print(f"  Trust label: {card.uahp_trust_label}")
    print(f"  Liveness:    {card.uahp_liveness}")
    print(f"  Completions: {card.uahp_total_completions}")

    # 10. Agent selection (best of candidates)
    print("\n[9] Agent selection...")
    best = a2a.select_agent([alice, bob], min_trust=0.3)
    print(f"  Best agent: {best.agent_id} ({best.metadata.get('name')})")

    # 11. Death certificate
    print("\n[10] Death certificate...")
    cert = uahp.declare_death(
        dead_agent_id=bob.agent_id,
        declared_by=alice.agent_id,
        reason="Unresponsive for 48 hours",
    )
    bob_status = uahp.is_alive(bob.agent_id)
    print(f"  Bob status: {bob_status.value}")
    print(f"  Declared by: {cert.declared_by}")
    print(f"  Reason: {cert.reason}")
    assert bob_status == AgentStatus.DEAD

    # 12. A2A death event
    death_event = a2a.death_certificate_to_a2a_event(bob.agent_id)
    print(f"  A2A event type: {death_event['type']}")

    # 13. MCP server tool test
    print("\n[11] MCP server tool routing...")
    from mcp_server import handle_request

    # Test tools/list
    response = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/list"
    })
    tools = response["result"]["tools"]
    print(f"  Available tools: {len(tools)}")

    # Test create identity via MCP
    response = handle_request({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {
            "name": "uahp_create_identity",
            "arguments": {"name": "Charlie", "description": "Test agent"},
        },
    })
    result = json.loads(response["result"]["content"][0]["text"])
    print(f"  Created via MCP: {result['agent_id']}")

    # Test trust score via MCP
    response = handle_request({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {
            "name": "uahp_trust_score",
            "arguments": {"agent_id": result["agent_id"]},
        },
    })
    score_result = json.loads(response["result"]["content"][0]["text"])
    print(f"  Trust (new agent): {score_result['trust_score']} ({score_result['label']})")

    print("\n" + "=" * 60)
    print("All tests passed.")


if __name__ == "__main__":
    test_full_stack()
