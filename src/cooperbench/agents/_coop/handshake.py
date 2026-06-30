"""C1 plan-handshake gate.

Before any agent may keep code edits, every coop agent must publish a plan
(send the partner a message). The gate is shared in-process across the two coop
agent threads; until it opens, the enforcement hook reverts edits and tells the
agent to publish its plan and wait for its partner. This forces a plan exchange
up front — the cheapest "structure" on the ladder.
"""

import threading


class HandshakeLedger:
    def __init__(self, agents) -> None:
        self._agents: set[str] = set(agents)
        self._planned: set[str] = set()
        self._lock = threading.Lock()

    def mark_planned(self, agent_id: str) -> None:
        """Record that ``agent_id`` published its plan (ignored if unknown)."""
        with self._lock:
            if agent_id in self._agents:
                self._planned.add(agent_id)

    def planned(self, agent_id: str) -> bool:
        with self._lock:
            return agent_id in self._planned

    def gate_open(self) -> bool:
        """True once every configured agent has published a plan."""
        with self._lock:
            return bool(self._agents) and self._agents <= self._planned
