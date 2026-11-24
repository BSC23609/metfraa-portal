"""Design Training course — runs on the shared training engine.

PEB design/engineering training. Content lives in
app/design_training_seed.py; the UI and endpoints come from
app/training_core.py.
"""
from ..models import (DesignLesson, DesignQuizQuestion,
                      DesignLessonProgress, DesignQuizAttempt)
from ..training_core import build_training_router

router = build_training_router(
    "/design-training",
    Lesson=DesignLesson, Question=DesignQuizQuestion,
    Progress=DesignLessonProgress, Attempt=DesignQuizAttempt,
    page_title="Design Training — Metfraa",
    heading="Design Training",
    subtitle="Learn how Metfraa engineers pre-engineered buildings — then test yourself.",
)
