"""Lifter configuration without undocumented physiological defaults."""

from dataclasses import dataclass
import math
from typing import Literal


@dataclass(frozen=True)
class LifterParams:
    """Explicit lifter inputs for the internal development simulator.

    Generation interprets progression as load units/session, noise as an absolute
    uniform half-width, and notes frequency as expected references/session.
    These are simulation design choices, not D3 indicator definitions.
    """

    sessions_per_week: int
    start_e1rm: float
    progression_rate: float
    noise: float
    units: Literal["kg", "lb"]
    rpe_habit: Literal["always", "sometimes", "never"]
    notes_frequency: float

    def __post_init__(self) -> None:
        if type(self.sessions_per_week) is not int or self.sessions_per_week < 0:
            raise ValueError("sessions_per_week must be a nonnegative integer")
        for name in ("start_e1rm", "progression_rate", "noise", "notes_frequency"):
            value = getattr(self, name)
            if type(value) not in (int, float):
                raise ValueError(f"{name} must be a finite number")
            try:
                converted = float(value)
            except OverflowError as exc:
                raise ValueError(f"{name} must be a finite number") from exc
            if not math.isfinite(converted):
                raise ValueError(f"{name} must be a finite number")
            object.__setattr__(self, name, converted)
        if self.start_e1rm <= 0:
            raise ValueError("start_e1rm must be positive")
        if self.noise < 0 or self.notes_frequency < 0:
            raise ValueError("noise magnitude and notes frequency cannot be negative")
        if self.units not in ("kg", "lb"):
            raise ValueError("units must be kg or lb")
        if self.rpe_habit not in ("always", "sometimes", "never"):
            raise ValueError("rpe_habit must be always, sometimes or never")
