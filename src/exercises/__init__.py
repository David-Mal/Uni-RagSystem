"""Exercise vocabulary and muscle mapping backed by free-exercise-db."""

from src.exercises.loader import (
    Exercise,
    ExerciseDiff,
    Muscle,
    diff,
    exercise_ids,
    load_exercises,
    muscle_weights,
)

__all__ = [
    "Exercise",
    "ExerciseDiff",
    "Muscle",
    "diff",
    "exercise_ids",
    "load_exercises",
    "muscle_weights",
]
