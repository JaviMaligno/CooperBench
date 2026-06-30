"""Unit tests for C1 plan-handshake gate (pure, no Docker)."""

from cooperbench.agents._coop.handshake import HandshakeLedger


class TestHandshakeLedger:
    def test_gate_closed_until_all_agents_publish_a_plan(self):
        led = HandshakeLedger(["agent_a", "agent_b"])
        assert led.gate_open() is False
        led.mark_planned("agent_a")
        assert led.planned("agent_a") is True
        assert led.gate_open() is False  # agent_b hasn't published
        led.mark_planned("agent_b")
        assert led.gate_open() is True

    def test_unknown_agent_marking_does_not_open_gate(self):
        led = HandshakeLedger(["agent_a", "agent_b"])
        led.mark_planned("agent_a")
        led.mark_planned("stranger")  # not one of the configured agents
        assert led.gate_open() is False

    def test_marking_is_idempotent(self):
        led = HandshakeLedger(["agent_a", "agent_b"])
        led.mark_planned("agent_a")
        led.mark_planned("agent_a")
        led.mark_planned("agent_b")
        assert led.gate_open() is True
