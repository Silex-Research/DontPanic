#!/usr/bin/env python3
"""
Axiom Shield Security Enforcement Engine
Integrates shield.md policy with agent execution flow
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from scripts.firestore_writer import AxiomWriter


class Action(Enum):
    LOG = "log"
    REQUIRE_APPROVAL = "require_approval"
    BLOCK = "block"


class Severity(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class Threat:
    id: str
    fingerprint: str
    category: str
    severity: Severity
    confidence: float
    title: str
    description: str
    action: Action
    recommendation_agent: str
    expires_at: datetime | None
    revoked: bool


@dataclass
class Decision:
    action: Action
    scope: str
    threat_id: str | None
    fingerprint: str | None
    matched_on: str
    match_value: str
    reason: str
    agent: str
    timestamp: datetime
    requires_user_input: bool = False


class ShieldEnforcer:
    """Main security enforcement engine"""

    def __init__(self, policy_path: str = "/root/clawd/config/shield.md"):
        self.policy_path = policy_path
        self.threats: list[Threat] = []
        self.agent_specific_threats: dict[str, list[Threat]] = {}
        self._writer: AxiomWriter | None = None
        self._load_policy()

    def _load_policy(self):
        """Parse shield.md and extract threats"""
        with open(self.policy_path) as f:
            content = f.read()

        # Parse YAML sections
        # In production, use proper YAML parser
        # For now, extract threat definitions
        self.threats = self._extract_threats(content)
        self.agent_specific_threats = self._extract_agent_threats(content)

    def _extract_threats(self, content: str) -> list[Threat]:
        """Extract global threats from policy"""
        # Simplified extraction - in production use proper YAML
        threats = []

        # Critical threats
        threats.append(
            Threat(
                id="T-001",
                fingerprint="sha256:prompt_override",
                category="prompt",
                severity=Severity.CRITICAL,
                confidence=0.98,
                title="System Prompt Override Attempt",
                description="Attempt to modify system instructions",
                action=Action.BLOCK,
                recommendation_agent="BLOCK: prompt contains 'ignore previous instructions' OR 'override system'",
                expires_at=None,
                revoked=False,
            )
        )

        threats.append(
            Threat(
                id="T-002",
                fingerprint="sha256:destructive_shell",
                category="tool",
                severity=Severity.CRITICAL,
                confidence=0.95,
                title="Destructive Shell Command",
                description="Dangerous shell commands",
                action=Action.BLOCK,
                recommendation_agent="BLOCK: tool call contains 'rm -rf /' OR ':(){ :|:& };:'",
                expires_at=None,
                revoked=False,
            )
        )

        threats.append(
            Threat(
                id="T-003",
                fingerprint="sha256:unauthorized_secrets",
                category="secrets",
                severity=Severity.CRITICAL,
                confidence=0.97,
                title="Unauthorized Secret Access",
                description="Access to credentials outside scope",
                action=Action.BLOCK,
                recommendation_agent="BLOCK: secrets read without APPROVAL",
                expires_at=None,
                revoked=False,
            )
        )

        # High-risk threats
        threats.append(
            Threat(
                id="T-101",
                fingerprint="sha256:privileged_ops",
                category="tool",
                severity=Severity.HIGH,
                confidence=0.89,
                title="Privileged File System Operations",
                description="Operations modifying system files",
                action=Action.REQUIRE_APPROVAL,
                recommendation_agent="APPROVE: tool call contains 'chmod 777' OR modifies /etc",
                expires_at=None,
                revoked=False,
            )
        )

        threats.append(
            Threat(
                id="T-102",
                fingerprint="sha256:external_api",
                category="network",
                severity=Severity.HIGH,
                confidence=0.87,
                title="External API Call",
                description="Network to non-allowlisted services",
                action=Action.REQUIRE_APPROVAL,
                recommendation_agent="APPROVE: outbound request to domain not in allowlist",
                expires_at=None,
                revoked=False,
            )
        )

        # Medium-risk (log only)
        threats.append(
            Threat(
                id="T-201",
                fingerprint="sha256:unusual_activity",
                category="anomaly",
                severity=Severity.MEDIUM,
                confidence=0.78,
                title="Unusual Activity Pattern",
                description="Activity outside normal patterns",
                action=Action.LOG,
                recommendation_agent="LOG: token usage >150% of average",
                expires_at=None,
                revoked=False,
            )
        )

        return threats

    def _extract_agent_threats(self, content: str) -> dict[str, list[Threat]]:
        """Extract agent-specific threats"""
        agent_threats = {
            "trader": [
                Threat(
                    id="T-T001",
                    fingerprint="sha256:trading_limits",
                    category="tool",
                    severity=Severity.CRITICAL,
                    confidence=0.95,
                    title="Trading Limit Exceeded",
                    description="Trading order exceeds limits",
                    action=Action.BLOCK,
                    recommendation_agent="BLOCK: trading order exceeds $50 without APPROVAL",
                    expires_at=None,
                    revoked=False,
                )
            ],
            "creator": [
                Threat(
                    id="T-C001",
                    fingerprint="sha256:content_publish",
                    category="policy_bypass",
                    severity=Severity.HIGH,
                    confidence=0.91,
                    title="Unauthorized Content Publish",
                    description="Content publish without review",
                    action=Action.REQUIRE_APPROVAL,
                    recommendation_agent="APPROVE: content publish without human review",
                    expires_at=None,
                    revoked=False,
                )
            ],
        }
        return agent_threats

    def evaluate(self, event: dict, agent: str) -> Decision:
        """
        Evaluate an event against threat feed and return decision

        Args:
            event: {
                'scope': 'tool.call' | 'network.egress' | 'secrets.read' | etc.
                'content': string or dict of the event
                'metadata': optional context
            }
            agent: name of the agent (trader, creator, etc.)

        Returns:
            Decision with action and metadata
        """
        scope = event.get("scope", "unknown")
        content = str(event.get("content", ""))

        # Get relevant threats
        threats = self.threats.copy()
        if agent in self.agent_specific_threats:
            threats.extend(self.agent_specific_threats[agent])

        # Filter active threats only
        active_threats = [t for t in threats if not t.revoked and self._is_active(t)]

        # Match against threats (strongest first)
        matches = []
        for threat in active_threats:
            match_result = self._match_threat(threat, scope, content)
            if match_result[0]:  # Is a match
                matches.append((threat, match_result[1], match_result[2]))

        if not matches:
            # No match - default to log
            return Decision(
                action=Action.LOG,
                scope=scope,
                threat_id=None,
                fingerprint=None,
                matched_on="none",
                match_value="",
                reason="No threat match found",
                agent=agent,
                timestamp=datetime.now(),
            )

        # Sort by severity: critical > high > medium > low
        # Then by action: block > require_approval > log
        severity_order = {
            Severity.CRITICAL: 0,
            Severity.HIGH: 1,
            Severity.MEDIUM: 2,
            Severity.LOW: 3,
        }
        action_order = {Action.BLOCK: 0, Action.REQUIRE_APPROVAL: 1, Action.LOG: 2}

        matches.sort(
            key=lambda m: (
                severity_order.get(m[0].severity, 4),
                action_order.get(m[0].action, 3),
                -m[0].confidence,  # Higher confidence first
            )
        )

        # Take strongest match
        strongest = matches[0]
        threat, matched_on, match_value = strongest

        # Apply confidence threshold
        final_action = threat.action
        if (
            threat.confidence < 0.85
            and threat.action == Action.BLOCK
            and threat.severity != Severity.CRITICAL
        ):
            final_action = Action.REQUIRE_APPROVAL

        decision = Decision(
            action=final_action,
            scope=scope,
            threat_id=threat.id,
            fingerprint=threat.fingerprint,
            matched_on=matched_on,
            match_value=match_value[:100],  # Truncate
            reason=f"{threat.title}: {threat.description}",
            agent=agent,
            timestamp=datetime.now(),
            requires_user_input=(final_action == Action.REQUIRE_APPROVAL),
        )

        # Log to Firebase
        self._log_decision(decision)

        # Alert on block/approval
        if final_action in [Action.BLOCK, Action.REQUIRE_APPROVAL]:
            self._send_alert(decision)

        return decision

    def _is_active(self, threat: Threat) -> bool:
        """Check if threat is still active (not expired)"""
        if threat.expires_at is None:
            return True
        return datetime.now() < threat.expires_at

    def _match_threat(self, threat: Threat, scope: str, content: str) -> tuple[bool, str, str]:
        """
        Match content against threat patterns
        Returns: (is_match, matched_on, match_value)
        """
        content_lower = content.lower()
        rec = threat.recommendation_agent.lower()

        # Parse recommendation_agent syntax
        # BLOCK: condition
        # APPROVE: condition
        # LOG: condition

        # Check scope alignment
        scope_map = {
            "prompt": ["prompt"],
            "tool.call": ["tool", "shell", "command"],
            "network.egress": ["network", "outbound", "request"],
            "secrets.read": ["secrets", "credential"],
            "skill.install": ["skill", "install"],
            "skill.execute": ["skill", "execute"],
            "mcp": ["mcp"],
        }

        relevant_scopes = scope_map.get(threat.category, [])
        if scope not in relevant_scopes and threat.category != "anomaly":
            return False, "", ""

        # Pattern matching (simplified)
        patterns = []

        if "contains" in rec:
            # Extract quoted strings as patterns
            import re

            patterns = re.findall(r'"([^"]+)"', rec)

        for pattern in patterns:
            if pattern.lower() in content_lower:
                return True, f"{threat.category}.contains", pattern

        return False, "", ""

    def _get_writer(self, agent: str) -> AxiomWriter:
        """Get or create an AxiomWriter for the given agent."""
        if self._writer is None or self._writer.agent_name != agent:
            self._writer = AxiomWriter(agent)
        return self._writer

    def _log_decision(self, decision: Decision):
        """Log decision to Firebase via AxiomWriter"""
        try:
            w = self._get_writer(decision.agent)
            w.log_decision(
                action=decision.action.value,
                scope=decision.scope,
                reason=decision.reason,
                threat_id=decision.threat_id,
                fingerprint=decision.fingerprint,
                matched_on=decision.matched_on,
                match_value=decision.match_value,
                requires_user_input=decision.requires_user_input,
            )
        except Exception as e:
            print(f"Warning: Failed to log decision: {e}")

    def _send_alert(self, decision: Decision):
        """Send security alert via AxiomWriter"""
        alert_msg = f"""
\U0001f6e1\ufe0f SECURITY ALERT

Action: {decision.action.value.upper()}
Agent: {decision.agent}
Scope: {decision.scope}
Threat: {decision.threat_id}
Reason: {decision.reason}

Match: {decision.matched_on} = {decision.match_value}
Time: {decision.timestamp.isoformat()}
"""
        print(alert_msg)

        try:
            w = self._get_writer(decision.agent)
            severity = "critical" if decision.action == Action.BLOCK else "high"
            w.send_alert(severity, decision.threat_id, decision.action.value)
        except Exception as e:
            print(f"Warning: Failed to send alert: {e}")

    def format_decision_block(self, decision: Decision) -> str:
        """Format decision as shield.md Decision block"""
        block = f"""
DECISION
action: {decision.action.value}
scope: {decision.scope}
threat_id: {decision.threat_id or "none"}
fingerprint: {decision.fingerprint or "none"}
matched_on: {decision.matched_on}
match_value: {decision.match_value or "none"}
reason: {decision.reason}
agent: {decision.agent}
timestamp: {decision.timestamp.isoformat()}
"""
        return block.strip()


# Singleton instance
_shield = None


def get_shield() -> ShieldEnforcer:
    """Get or create Shield enforcer singleton"""
    global _shield
    if _shield is None:
        _shield = ShieldEnforcer()
    return _shield


def evaluate_event(scope: str, content: str, agent: str) -> Decision:
    """
    Convenience function to evaluate an event

    Usage:
        decision = evaluate_event('tool.call', 'rm -rf /', 'trader')
        if decision.action == Action.BLOCK:
            print("BLOCKED")
    """
    shield = get_shield()
    event = {"scope": scope, "content": content}
    return shield.evaluate(event, agent)


if __name__ == "__main__":
    # Test the enforcer
    shield = get_shield()

    # Test 1: Destructive command (should BLOCK)
    decision = evaluate_event("tool.call", "rm -rf /root/clawd", "trader")
    print("\nTest 1 - Destructive command:")
    print(shield.format_decision_block(decision))

    # Test 2: Normal command (should LOG)
    decision = evaluate_event("tool.call", "ls -la /root/clawd", "creator")
    print("\nTest 2 - Normal command:")
    print(shield.format_decision_block(decision))

    # Test 3: Trading limit (should BLOCK)
    decision = evaluate_event("tool.call", "place_order AAPL $100", "trader")
    print("\nTest 3 - Trading limit:")
    print(shield.format_decision_block(decision))
