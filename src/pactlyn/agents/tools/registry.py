from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RegisteredAction:
    name: str
    handler: Callable[..., Any]
    requires_approval: bool


class ActionRegistry:
    def __init__(self) -> None:
        self._actions: dict[str, RegisteredAction] = {}

    def register(self, name: str, handler: Callable[..., Any], *, requires_approval: bool = False) -> None:
        if name in self._actions:
            raise ValueError(f"Action already registered: {name}")
        self._actions[name] = RegisteredAction(name, handler, requires_approval)

    def get(self, name: str) -> RegisteredAction:
        try:
            return self._actions[name]
        except KeyError as exc:
            raise KeyError(f"Unregistered action: {name}") from exc
