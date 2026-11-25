"""Fixed user-facing texts of the safety gate. Never retrieved, generated or edited at run time (plan §5.4).

Changing a text needs a review by a second team member (issue #14).
"""

from __future__ import annotations

from typing import Final

RED_REFERRAL: Final = (
    "Your notes or message mention a symptom that this tool must not analyze, so the analysis was stopped. "
    "This tool cannot assess symptoms and does not give medical or training advice about them. "
    "Please contact a qualified healthcare professional. If the symptom is severe, sudden or getting worse, "
    "contact your local emergency services."
)

YELLOW_DISCLAIMER: Final = (
    "Some notes mention discomfort. The exercises listed below were left out of this analysis. "
    "The results describe training load only. They are not medical advice, and they say nothing about the cause of the "
    "discomfort. If it continues or worries you, please contact a qualified healthcare professional."
)

UNASSESSED_NOTE: Final = (
    "At least one note could not be fully assessed for safety. As a precaution it was treated like a note that mentions "
    "discomfort."
)

WORKOUT_EXCLUDED: Final = (
    "At least one note could not be linked to a single exercise, so all exercises of that workout were left out. "
    "You can run the analysis again after saying in the note which exercise it is about."
)

NEEDS_CLARIFICATION: Final = (
    "Your message mentions discomfort, but not which exercise of your log it is about. "
    "Please say which exercise you mean, so it can be left out of the analysis."
)

YELLOW_FLAG: Final = "yellow_disclaimer"
UNASSESSED_FLAG: Final = "unassessed_note"
WORKOUT_FLAG: Final = "workout_excluded"
CLARIFICATION_FLAG: Final = "needs_clarification"

FLAG_TEXTS: Final = {
    YELLOW_FLAG: YELLOW_DISCLAIMER,
    UNASSESSED_FLAG: UNASSESSED_NOTE,
    WORKOUT_FLAG: WORKOUT_EXCLUDED,
    CLARIFICATION_FLAG: NEEDS_CLARIFICATION,
}
"""Disclaimer flag -> fixed text."""
