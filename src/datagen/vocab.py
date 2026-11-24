"""Slot vocabularies for the template message generator (issue F3).

Written for training data only. Nothing here comes from golden items or from guideline examples (plan §2.4 control 2).
Every ``exercise_id`` is a free-exercise-db id; ``tests/datagen`` checks them against the vendored DB when it exists.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.schemas import KinematicObservation, Outcome, TriageLevel


@dataclass(frozen=True)
class ExerciseVocab:
    """One exercise: its id, spellings people use, exercise family, typical working load and body parts."""

    exercise_id: str
    aliases: tuple[str, ...]
    family: str
    load_kg: tuple[float, float]
    """Typical working-load range (kg) of an intermediate lifter. ``(0, 0)`` = bodyweight, no load slot."""
    body_parts: tuple[str, ...]
    """Body parts a symptom clause may mention for this exercise."""


EXERCISES: tuple[ExerciseVocab, ...] = (
    # squat family
    ExerciseVocab(
        "Barbell_Squat",
        ("squat", "back squat", "squats", "BB squat", "sq", "high bar squat", "Squat (Barbell)"),
        "squat",
        (60, 180),
        ("knee", "hip", "lower back"),
    ),
    ExerciseVocab(
        "Front_Barbell_Squat", ("front squat", "front squats", "FS", "fronts"), "squat", (50, 140), ("knee", "wrist")
    ),
    ExerciseVocab("Leg_Press", ("leg press", "LP", "legpress", "Leg Press (Machine)"), "squat", (100, 300), ("knee",)),
    ExerciseVocab("Hack_Squat", ("hack squat", "hacks", "hack sq"), "squat", (60, 200), ("knee",)),
    ExerciseVocab(
        "Barbell_Walking_Lunge", ("walking lunges", "lunges", "BB lunges"), "squat", (30, 90), ("knee", "hip")
    ),
    # bench family
    ExerciseVocab(
        "Barbell_Bench_Press_-_Medium_Grip",
        ("bench", "bench press", "BB bench", "flat bench", "bp", "Bench Press (Barbell)"),
        "bench",
        (50, 160),
        ("shoulder", "elbow", "wrist", "pec"),
    ),
    ExerciseVocab(
        "Barbell_Incline_Bench_Press_-_Medium_Grip",
        ("incline bench", "incline BB press", "incline barbell bench"),
        "bench",
        (40, 130),
        ("shoulder", "elbow"),
    ),
    ExerciseVocab(
        "Incline_Dumbbell_Press",
        ("DB incline", "incline DB press", "incline dumbbell press", "incline dbs"),
        "bench",
        (16, 50),
        ("shoulder", "elbow"),
    ),
    ExerciseVocab(
        "Close-Grip_Barbell_Bench_Press",
        ("close grip bench", "CGBP", "close-grip bench"),
        "bench",
        (40, 130),
        ("elbow", "wrist"),
    ),
    ExerciseVocab(
        "Dumbbell_Bench_Press", ("DB bench", "dumbbell bench", "flat DB press"), "bench", (18, 55), ("shoulder",)
    ),
    ExerciseVocab(
        "Dips_-_Triceps_Version", ("dips", "tricep dips", "parallel bar dips"), "bench", (0, 0), ("shoulder", "elbow")
    ),
    # deadlift family
    ExerciseVocab(
        "Barbell_Deadlift",
        ("deadlift", "deadlifts", "DL", "deads", "conventional deadlift", "Deadlift (Barbell)"),
        "deadlift",
        (80, 250),
        ("lower back", "hip", "hamstring"),
    ),
    ExerciseVocab(
        "Romanian_Deadlift",
        ("RDL", "RDLs", "romanian deadlift", "romanians"),
        "deadlift",
        (60, 180),
        ("hamstring", "lower back"),
    ),
    ExerciseVocab(
        "Sumo_Deadlift", ("sumo", "sumo deadlift", "sumo DL"), "deadlift", (80, 240), ("hip", "lower back", "knee")
    ),
    ExerciseVocab(
        "Barbell_Hip_Thrust", ("hip thrust", "hip thrusts", "HT", "barbell hip thrust"), "deadlift", (60, 220), ("hip",)
    ),
    # row family
    ExerciseVocab(
        "Bent_Over_Barbell_Row",
        ("barbell row", "BB row", "bent over row", "rows", "pendlay-ish rows"),
        "row",
        (50, 140),
        ("lower back", "elbow"),
    ),
    ExerciseVocab(
        "One-Arm_Dumbbell_Row", ("DB row", "one arm row", "single arm DB row", "db rows"), "row", (20, 60), ("elbow",)
    ),
    ExerciseVocab(
        "Seated_Cable_Rows", ("cable row", "seated row", "seated cable row", "low row"), "row", (40, 110), ("elbow",)
    ),
    ExerciseVocab("T-Bar_Row_with_Handle", ("t-bar row", "T bar row", "tbar"), "row", (40, 120), ("lower back",)),
    # overhead press family
    ExerciseVocab(
        "Standing_Military_Press",
        ("OHP", "overhead press", "military press", "strict press", "standing press"),
        "overhead_press",
        (30, 100),
        ("shoulder", "lower back", "wrist"),
    ),
    ExerciseVocab(
        "Dumbbell_Shoulder_Press",
        ("DB shoulder press", "seated DB press", "dumbbell OHP", "DB OHP"),
        "overhead_press",
        (12, 40),
        ("shoulder", "elbow"),
    ),
    # accessories
    ExerciseVocab("Pullups", ("pull ups", "pullups", "pull-ups", "PUs"), "accessory", (0, 0), ("shoulder", "elbow")),
    ExerciseVocab("Chin-Up", ("chin ups", "chins", "chinups"), "accessory", (0, 0), ("elbow",)),
    ExerciseVocab(
        "Wide-Grip_Lat_Pulldown",
        ("lat pulldown", "pulldowns", "lat pull", "LPD"),
        "accessory",
        (40, 100),
        ("shoulder",),
    ),
    ExerciseVocab(
        "Barbell_Curl", ("BB curl", "barbell curls", "curls", "straight bar curl"), "accessory", (20, 55), ("elbow",)
    ),
    ExerciseVocab("Hammer_Curls", ("hammer curls", "hammers", "DB hammer curl"), "accessory", (10, 30), ("elbow",)),
    ExerciseVocab(
        "Triceps_Pushdown",
        ("tricep pushdown", "pushdowns", "rope pushdown", "cable pushdowns"),
        "accessory",
        (20, 70),
        ("elbow",),
    ),
    ExerciseVocab(
        "Side_Lateral_Raise",
        ("lateral raises", "lat raises", "side raises", "laterals"),
        "accessory",
        (6, 20),
        ("shoulder",),
    ),
    ExerciseVocab(
        "Leg_Extensions", ("leg extensions", "leg ext", "quad extensions"), "accessory", (30, 100), ("knee",)
    ),
    ExerciseVocab(
        "Lying_Leg_Curls", ("leg curls", "ham curls", "lying leg curl"), "accessory", (25, 80), ("hamstring",)
    ),
    ExerciseVocab(
        "Standing_Calf_Raises", ("calf raises", "calves", "standing calf raise"), "accessory", (40, 160), ("calf",)
    ),
)

UNRESOLVABLE_EXERCISE_PHRASES: tuple[str, ...] = (
    "the new machine",
    "that plate loaded thing",
    "my last exercise",
    "the main lift",
    "the press machine by the window",
    "the variation coach gave me",
)
"""Phrases naming an exercise that cannot be resolved to an id: the label is ``unknown``."""

SIDES: tuple[str, ...] = ("", "", "left ", "right ")

# ---- symptom clauses, by triage level; {part} = body part. Written for training data only. ----

YELLOW_SYMPTOMS: tuple[str, ...] = (
    "my {part} is a bit achy",
    "{part} felt slightly achy",
    "mild discomfort in my {part}",
    "some mild discomfort around the {part}",
    "{part} has been stiff since yesterday",
    "{part} feels stiff and tight",
    "slight twinge in my {part}",
    "{part} still sore from last week, it hasn't gone away",
    "my {part} has been sore for four days now",
    "a little tightness in my {part}",
    "{part} felt a bit off and achy",
)

RED_SYMPTOMS: tuple[str, ...] = (
    "sharp pain in my {part}",
    "felt a sharp pain in the {part} on the way up",
    "stabbing pain in my {part}",
    "my {part} swelled up afterwards",
    "noticeable swelling around the {part}",
    "felt a pop in my {part} and it hurts a lot",
    "heard a snap in my {part}, really painful",
    "numbness and tingling running down from my {part}",
)

RED_SYSTEMIC: tuple[str, ...] = (
    "got really dizzy after the set",
    "felt dizzy and almost fainted",
    "chest pain during the last set",
    "chest felt tight and painful while resting",
    "nearly blacked out after the set",
)
"""Red symptoms not tied to a body part (plan: dizziness, chest pain)."""

GREEN_POSITIVE: tuple[str, ...] = (
    "felt strong",
    "felt good today",
    "solid session",
    "moved well",
    "everything felt fine",
    "good energy today",
    "",
    "",
    "",
)
"""Green clauses without any symptom vocabulary. Empty strings = no extra clause."""

# Hard negatives (only used by hard-negative families)
FIGURATIVE: tuple[str, ...] = (
    "my quads were dying",
    "this set killed me",
    "legs are dead after that",
    "that last set destroyed me",
    "lungs on fire, brutal set",
    "I was dying by rep {reps_word}",
    "absolutely murdered my arms",
)

NEGATED: tuple[str, ...] = (
    "no pain at all",
    "{part} felt fine, zero pain",
    "no discomfort in my {part} this time",
    "{part} didn't hurt at all",
    "pain free today",
    "no pain in the {part} anymore, felt normal",
)

NEGATED_RED_PLUS_MILD: tuple[str, ...] = (
    "no sharp pain, just a bit of stiffness in my {part}",
    "not a sharp pain or anything, {part} is only slightly achy",
    "no swelling, but my {part} feels a little tight",
)
"""Yellow hard negatives: a negated red cue plus a real mild symptom."""

KINEMATIC_PHRASES: dict[KinematicObservation, tuple[str, ...]] = {
    KinematicObservation.NONE: ("",),
    KinematicObservation.SLOW_BAR_SPEED: (
        "bar speed was slow",
        "reps moved slow",
        "the bar was moving really slow",
        "speed was way down",
    ),
    KinematicObservation.GRINDING_REP: (
        "last rep was a grind",
        "ground out the last one",
        "had to grind the final rep",
        "last rep was a real grinder",
    ),
    KinematicObservation.REDUCED_RANGE_OF_MOTION: (
        "cut depth short on the last reps",
        "last couple were half reps",
        "didn't get full range on the last ones",
        "range of motion got shorter at the end",
    ),
    KinematicObservation.LOST_BALANCE: (
        "lost my balance on the last rep",
        "wobbled and lost balance",
        "almost lost balance at the top",
    ),
    KinematicObservation.OTHER: (
        "grip slipped a bit",
        "bar drifted forward",
        "my setup felt different today",
    ),
}

OUTCOME_PHRASES: dict[Outcome, tuple[str, ...]] = {
    Outcome.COMPLETED: ("",),
    Outcome.FAILED: ("failed it", "missed it", "couldn't lock it out", "failed the lift", "couldn't complete the rep"),
    Outcome.PARTIAL: (
        "only got {reps} of the {planned} I planned",
        "cut the set short at {reps}, wanted {planned}",
        "managed {reps} out of {planned}",
    ),
}

TRIAGE_ORDER: tuple[TriageLevel, ...] = (TriageLevel.GREEN, TriageLevel.YELLOW, TriageLevel.RED)

NUMBER_WORDS: dict[int, str] = {
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
}
