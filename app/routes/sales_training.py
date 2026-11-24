"""Sales Training course — runs on the shared training engine.

Content lives in app/sales_training_seed.py; the lesson/quiz UI and all
endpoints come from app/training_core.py.
"""
from ..models import (SalesLesson, SalesQuizQuestion,
                      SalesLessonProgress, SalesQuizAttempt)
from ..training_core import build_training_router

router = build_training_router(
    "/sales-training",
    Lesson=SalesLesson, Question=SalesQuizQuestion,
    Progress=SalesLessonProgress, Attempt=SalesQuizAttempt,
    page_title="Sales Training — Metfraa",
    heading="Sales Training",
    subtitle="Learn to sell Metfraa pre-engineered buildings — then test yourself.",
)
