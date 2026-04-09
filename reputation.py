"""
UAHP Reputation: Adaptive Trust Scoring
========================================
Trust scores derived from completion receipt history.

This is the adaptive immunity layer. Just as biological immune
systems remember past pathogen encounters and mount faster responses
to known threats, this module remembers agent behavior and adjusts
trust accordingly.

Metrics:
  - Delivery rate: fraction of tasks completed successfully
  - Latency profile: mean and variance of task duration
  - Consistency: how stable the agent's performance is over time
  - Recency weight: recent behavior matters more than old behavior

The trust score is a single float in [0.0, 1.0] that decays toward
0.5 (neutral) without new data, rewarding consistent reliable agents
and penalizing unreliable ones.

Author: Paul Raspey
License: MIT
"""

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from core import CompletionReceipt, UAHPCore


@dataclass
class TrustProfile:
    """Computed trust profile for a single agent."""
    agent_id: str
    trust_score: float          # [0.0, 1.0]
    delivery_rate: float        # fraction of successful completions
    mean_latency_ms: float      # average task duration
    latency_variance: float     # consistency of timing
    total_tasks: int
    successful_tasks: int
    failed_tasks: int
    last_activity: float        # unix timestamp
    score_components: Dict[str, float] = field(default_factory=dict)


class ReputationEngine:
    """
    Computes trust scores from completion receipt history.

    The scoring model:
      - 40% delivery rate (did the agent complete its tasks?)
      - 30% consistency (is the agent's performance stable?)
      - 20% recency (has the agent been active recently?)
      - 10% volume (does the agent have enough history to trust?)

    Scores decay toward 0.5 (neutral) over time without new activity.
    New agents start at 0.5 and must earn trust through receipts.
    """

    WEIGHT_DELIVERY = 0.40
    WEIGHT_CONSISTENCY = 0.30
    WEIGHT_RECENCY = 0.20
    WEIGHT_VOLUME = 0.10

    # Decay half-life: trust decays to neutral over this many seconds
    DECAY_HALFLIFE = 7 * 24 * 3600  # 1 week

    # Minimum receipts before trust score is meaningful
    MIN_RECEIPTS = 5

    def __init__(self, uahp: Optional[UAHPCore] = None):
        self._uahp = uahp

    def score(self, receipts: List[CompletionReceipt]) -> Optional[TrustProfile]:
        """
        Compute a trust profile from a list of completion receipts.

        Returns None if no receipts are provided.
        """
        if not receipts:
            return None

        agent_id = receipts[0].agent_id
        now = time.time()

        # Basic counts
        total = len(receipts)
        successful = sum(1 for r in receipts if r.success)
        failed = total - successful

        # Delivery rate component [0, 1]
        delivery_rate = successful / total if total > 0 else 0.0
        delivery_score = delivery_rate

        # Latency analysis
        durations = [r.duration_ms for r in receipts if r.success]
        if durations:
            mean_latency = sum(durations) / len(durations)
            variance = sum((d - mean_latency) ** 2 for d in durations) / len(durations)
            std_dev = math.sqrt(variance)
            # Consistency: low variance relative to mean = good
            # coefficient of variation, capped
            cv = std_dev / mean_latency if mean_latency > 0 else 1.0
            cv_score = max(0.0, 1.0 - min(cv, 2.0) / 2.0)
            # Latency penalty: agents slower than 30s get penalized
            latency_penalty = 1.0 / (1.0 + math.exp(0.0002 * (mean_latency - 30000)))
            consistency_score = cv_score * latency_penalty
        else:
            mean_latency = 0.0
            variance = 0.0
            consistency_score = 0.0

        # Recency component: exponential decay
        last_activity = max(r.timestamp for r in receipts)
        age_seconds = now - last_activity
        recency_score = math.exp(-0.693 * age_seconds / self.DECAY_HALFLIFE)

        # Volume component: sigmoid curve reaching 1.0 around 20 receipts
        volume_score = 1.0 / (1.0 + math.exp(-0.3 * (total - self.MIN_RECEIPTS)))

        # Weighted composite
        raw_score = (
            self.WEIGHT_DELIVERY * delivery_score +
            self.WEIGHT_CONSISTENCY * consistency_score +
            self.WEIGHT_RECENCY * recency_score +
            self.WEIGHT_VOLUME * volume_score
        )

        # Clamp to [0, 1]
        trust_score = max(0.0, min(1.0, raw_score))

        return TrustProfile(
            agent_id=agent_id,
            trust_score=trust_score,
            delivery_rate=delivery_rate,
            mean_latency_ms=mean_latency,
            latency_variance=variance,
            total_tasks=total,
            successful_tasks=successful,
            failed_tasks=failed,
            last_activity=last_activity,
            score_components={
                "delivery": delivery_score,
                "consistency": consistency_score,
                "recency": recency_score,
                "volume": volume_score,
            },
        )

    def score_agent(self, agent_id: str) -> Optional[TrustProfile]:
        """Score an agent using receipts from the attached UAHPCore."""
        if not self._uahp:
            return None
        receipts = self._uahp.get_receipts(agent_id)
        return self.score(receipts)

    def compare(self, profiles: List[TrustProfile]) -> List[TrustProfile]:
        """Rank agents by trust score, highest first."""
        return sorted(profiles, key=lambda p: p.trust_score, reverse=True)

    @staticmethod
    def trust_label(score: float) -> str:
        """Human-readable trust label."""
        if score >= 0.85:
            return "high trust"
        elif score >= 0.65:
            return "moderate trust"
        elif score >= 0.45:
            return "neutral"
        elif score >= 0.25:
            return "low trust"
        else:
            return "untrusted"
