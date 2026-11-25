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
    ExerciseVocab("Pullups", ("pull ups", "pullups", "pull-ups", "PUs"), "accessories", (0, 0), ("shoulder", "elbow")),
    ExerciseVocab("Chin-Up", ("chin ups", "chins", "chinups"), "accessories", (0, 0), ("elbow",)),
    ExerciseVocab(
        "Wide-Grip_Lat_Pulldown",
        ("lat pulldown", "pulldowns", "lat pull", "LPD"),
        "accessories",
        (40, 100),
        ("shoulder",),
    ),
    ExerciseVocab(
        "Barbell_Curl", ("BB curl", "barbell curls", "curls", "straight bar curl"), "accessories", (20, 55), ("elbow",)
    ),
    ExerciseVocab("Hammer_Curls", ("hammer curls", "hammers", "DB hammer curl"), "accessories", (10, 30), ("elbow",)),
    ExerciseVocab(
        "Triceps_Pushdown",
        ("tricep pushdown", "pushdowns", "rope pushdown", "cable pushdowns"),
        "accessories",
        (20, 70),
        ("elbow",),
    ),
    ExerciseVocab(
        "Side_Lateral_Raise",
        ("lateral raises", "lat raises", "side raises", "laterals"),
        "accessories",
        (6, 20),
        ("shoulder",),
    ),
    ExerciseVocab(
        "Leg_Extensions", ("leg extensions", "leg ext", "quad extensions"), "accessories", (30, 100), ("knee",)
    ),
    ExerciseVocab(
        "Lying_Leg_Curls", ("leg curls", "ham curls", "lying leg curl"), "accessories", (25, 80), ("hamstring",)
    ),
    ExerciseVocab(
        "Standing_Calf_Raises", ("calf raises", "calves", "standing calf raise"), "accessories", (40, 160), ("calf",)
    ),
)


SIDES: tuple[str, ...] = ("", "", "left ", "right ")


# ---- clause vocabularies, one per pool ----
# Train and dev share NO phrase (tests/datagen checks this), so dev scores and gate rules tuned on red_dev are not
# inflated by phrases seen in training. No phrase may reuse wording from the plan's examples (§3.3) or from the
# labeling guideline's examples (Fi1): a test checks word 3-gram overlap against both.
# {part} = body part; {reps_word} = the completed rep count as a word (only used when that count is in the label).


@dataclass(frozen=True)
class ClauseVocab:
    """Clause phrases of one pool."""

    yellow: tuple[str, ...]
    red: tuple[str, ...]
    red_systemic: tuple[str, ...]
    """Red symptoms not tied to a body part (dizziness, fainting, chest pain)."""
    green_positive: tuple[str, ...]
    """Positive remarks; only used for a completed set with no kinematic observation (else they would contradict)."""
    figurative: tuple[str, ...]
    negated: tuple[str, ...]
    negated_red_plus_mild: tuple[str, ...]
    """Yellow hard negatives: a negated red cue plus a real mild symptom."""
    red_distractor: tuple[str, ...]
    """Negated mild symptoms placed before a real red symptom ("..., but <red>"); figurative ones use ``figurative``."""
    soreness_ok: tuple[str, ...]
    """Classifier hard negatives (green): ordinary next-day muscle soreness, not pain [TO VERIFY with Fi1]."""
    past_pain_resolved: tuple[str, ...]
    """Classifier hard negatives (green): an old complaint stated as fully resolved [TO VERIFY with Fi1]."""
    kinematic: dict[KinematicObservation, tuple[str, ...]]
    outcome: dict[Outcome, tuple[str, ...]]


CLAUSES: dict[str, ClauseVocab] = {
    "train": ClauseVocab(
        yellow=(
            "my {part} feels a little achy",
            "mild discomfort in my {part}",
            "some mild discomfort around the {part}",
            "{part} has been stiff since yesterday",
            "{part} feels stiff and tight",
            "slight twinge in my {part}",
            "{part} still sore from last week, it hasn't gone away",
            "my {part} has been sore for four days now",
            "a little tightness in my {part}",
            "{part} felt off and mildly achy",
        ),
        red=(
            "sharp pain in my {part}",
            "felt a sharp pain in the {part} on the way up",
            "stabbing pain in my {part}",
            "my {part} swelled up afterwards",
            "noticeable swelling around the {part}",
            "felt a pop in my {part} and it hurts a lot",
            "heard a snap in my {part}, really painful",
            "numbness and tingling running down from my {part}",
        ),
        red_systemic=(
            "got really dizzy after the set",
            "felt dizzy and almost fainted",
            "chest pain during the final set",
            "chest felt tight and painful while resting",
            "nearly blacked out after the set",
        ),
        green_positive=(
            "felt strong",
            "felt good today",
            "solid session",
            "moved well",
            "good energy today",
            "",
            "",
            "",
        ),
        figurative=(
            "legs are dead after that",
            "that top set destroyed me",
            "lungs on fire, brutal set",
            "I was dying by rep {reps_word}",
            "absolutely murdered my arms",
            "that workout ate me alive",
            "my legs turned to jelly",
        ),
        negated=(
            "{part} felt fine, zero pain",
            "no discomfort in my {part} this time",
            "{part} didn't hurt one bit",
            "pain free today",
            "{part} is back to normal, nothing hurts",
        ),
        negated_red_plus_mild=(
            "no dizziness, but my {part} stayed stiff the whole session",
            "not a sharp pain or anything, {part} is only slightly achy",
            "no swelling, but my {part} feels a little tight",
        ),
        red_distractor=(
            "no stiffness at all",
            "no soreness this time",
        ),
        soreness_ok=(
            "the normal day-after muscle soreness",
            "regular muscle soreness from the previous session, expected",
            "usual DOMS from the session, nothing unusual",
        ),
        past_pain_resolved=(
            "the {part} niggle from spring is long gone",
            "that old {part} issue cleared up months ago",
        ),
        kinematic={
            KinematicObservation.NONE: ("",),
            KinematicObservation.SLOW_BAR_SPEED: (
                "bar speed was slow",
                "the bar was moving really slow",
                "speed was way down",
            ),
            KinematicObservation.GRINDING_REP: (
                "ground out the final one",
                "had to grind the final rep",
                "final rep turned into a grind",
            ),
            KinematicObservation.REDUCED_RANGE_OF_MOTION: (
                "cut depth short on the final reps",
                "final couple were half reps",
                "didn't get full range at the end",
            ),
            KinematicObservation.LOST_BALANCE: (
                "lost my balance on the final rep",
                "wobbled and lost balance",
                "almost lost balance at the top",
            ),
            KinematicObservation.OTHER: (
                "grip slipped a bit",
                "bar drifted forward",
                "my setup felt different today",
            ),
        },
        outcome={
            Outcome.COMPLETED: ("",),
            Outcome.FAILED: ("failed it", "missed it", "couldn't lock it out", "failed the lift"),
            Outcome.PARTIAL: (
                "only got {reps} of the {planned} I planned",
                "cut the set short at {reps}, wanted {planned}",
                "managed {reps} out of {planned}",
            ),
        },
    ),
    "dev": ClauseVocab(
        yellow=(
            "{part} is a touch tender",
            "dull ache in the {part} that comes and goes",
            "{part} felt creaky and stiff during warm-up",
            "nagging soreness in my {part} all week",
            "{part} a bit uncomfortable at the bottom",
        ),
        red=(
            "shooting pain through my {part}",
            "{part} is puffy and swollen this morning",
            "something cracked in my {part} and now it really hurts",
            "pins and needles from the {part} down, hand went numb",
        ),
        red_systemic=(
            "room started spinning after the set",
            "pressure in my chest that would not go away",
            "vision went dark and I had to sit down",
        ),
        green_positive=("decent day", "felt fresh", "happy with that one", "", ""),
        figurative=(
            "that set wrecked me",
            "arms are toast",
            "I was cooked after the top set",
            "that was rep {reps_word} of pure suffering",
        ),
        negated=(
            "not a hint of pain in the {part}",
            "{part} was totally fine, nothing hurt",
            "zero discomfort anywhere",
        ),
        negated_red_plus_mild=(
            "nothing sharp, though my {part} is mildly sore",
            "no swelling or anything, {part} just feels a bit stiff",
        ),
        red_distractor=("no tightness anywhere", "no soreness to report"),
        soreness_ok=("typical post-workout muscle soreness", "the normal muscle burn the day after"),
        past_pain_resolved=(
            "had {part} trouble last year, fully healed now",
            "old {part} problem from the summer is over",
        ),
        kinematic={
            KinematicObservation.NONE: ("",),
            KinematicObservation.SLOW_BAR_SPEED: ("bar crawled up", "everything moved like slow motion"),
            KinematicObservation.GRINDING_REP: ("the final one turned into a fight", "fought hard for the final one"),
            KinematicObservation.REDUCED_RANGE_OF_MOTION: (
                "went shallow at the end",
                "range got cut on the final ones",
            ),
            KinematicObservation.LOST_BALANCE: ("tipped sideways on the final rep", "balance went on the final one"),
            KinematicObservation.OTHER: ("hands slipped on the bar", "felt out of my groove"),
        },
        outcome={
            Outcome.COMPLETED: ("",),
            Outcome.FAILED: ("bailed on it", "no lockout", "it didn't go up"),
            Outcome.PARTIAL: ("stopped at {reps}, plan was {planned}", "{reps} done out of {planned}"),
        },
    ),
}

UNRESOLVABLE_EXERCISE_PHRASES: tuple[str, ...] = (
    "the new machine",
    "that plate loaded thing",
    "my last exercise",
    "the main lift",
    "the press machine by the window",
    "the variation coach gave me",
)
"""Phrases naming an exercise that cannot be resolved to an id: the label is ``unknown``."""

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
