"""Steering a running turn: text that joins it before its next model call.

A product steers through ``utils.capabilities.TURN_STEERING``: before each
model call after the run's first, the filter takes what was steered into the
conversation, appends it to the durable session where the run has reached
(the SDK has saved the previous step's items by then; the first call is
skipped because the SDK saves the run's own input only after it) and to the
model's input, and keeps each at that point for the run's later calls, whose
input the SDK rebuilds from the run's own items."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

Take = Callable[[str], Awaitable[List[str]]]


class SteeringFilter:
    def __init__(self, conversation_id: str, take: Take, session: Any) -> None:
        self._conversation_id = conversation_id
        self._take = take
        self._session = session
        self._calls = 0
        # (index in the SDK's own input, item) for each steered message.
        self._pinned: List[Tuple[int, Dict[str, Any]]] = []

    async def __call__(self, data: Any) -> Any:
        from agents.run_config import ModelInputData

        base = list(data.model_data.input)
        self._calls += 1
        if self._calls > 1:
            texts = await self._take(self._conversation_id)
            if texts:
                items = [{"role": "user", "content": text} for text in texts]
                if self._session is not None:
                    await self._session.add_items(items)
                self._pinned.extend((len(base), item) for item in items)
        if not self._pinned:
            return data.model_data
        out: List[Any] = []
        pins = iter(self._pinned)
        pin = next(pins, None)
        for index, item in enumerate(base + [None]):
            while pin is not None and pin[0] == index:
                out.append(pin[1])
                pin = next(pins, None)
            if index < len(base):
                out.append(item)
        return ModelInputData(input=out, instructions=data.model_data.instructions)


def filter_for(conversation_id: Optional[str], session: Any) -> Optional[SteeringFilter]:
    """A run's steering filter, when a product steers turns."""
    from utils.capabilities import TURN_STEERING, capability

    take = capability(TURN_STEERING)
    if take is None or not conversation_id:
        return None
    return SteeringFilter(conversation_id, take, session)
