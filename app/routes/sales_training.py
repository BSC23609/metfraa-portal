"""Sales Training — an interactive learn-and-test module for the Metfraa team.

Lessons are grouped into tracks (Foundations → Product & Value → Selling
Metfraa). Any logged-in user can work through the lessons, mark them complete,
and take the quiz; their progress and best quiz score are tracked per user.

Content is seeded (see app/sales_training_seed.py) and self-heals on startup.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from fastapi.templating import Jinja2Templates

from ..database import get_db
from ..deps import get_current_user
from ..models import (Employee, SalesLesson, SalesLessonProgress,
                      SalesQuizAttempt, SalesQuizQuestion)

router = APIRouter(prefix="/sales-training", tags=["sales-training"])
templates = Jinja2Templates(directory="app/templates")

PASS_PCT = 70   # score needed to "pass" the quiz


# ------------------------------------------------------------------ page
@router.get("/", response_class=HTMLResponse)
def page(request: Request, user: Employee = Depends(get_current_user),
         db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "sales_training.html", {"user": user})


# ------------------------------------------------------------------ overview
@router.get("/api/overview")
def api_overview(user: Employee = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    lessons = (db.query(SalesLesson).filter(SalesLesson.active == True)  # noqa: E712
               .order_by(SalesLesson.track_order, SalesLesson.sort_order).all())
    done_ids = {p.lesson_id for p in db.query(SalesLessonProgress.lesson_id)
                .filter(SalesLessonProgress.employee_id == user.id).all()}

    tracks: list[dict] = []
    by_track: dict[str, dict] = {}
    for ls in lessons:
        t = by_track.get(ls.track)
        if not t:
            t = {"track": ls.track, "track_order": ls.track_order, "lessons": []}
            by_track[ls.track] = t
            tracks.append(t)
        t["lessons"].append({
            "id": ls.id, "code": ls.code, "title": ls.title, "summary": ls.summary,
            "est_minutes": ls.est_minutes, "level": ls.level,
            "done": ls.id in done_ids,
        })
    tracks.sort(key=lambda x: x["track_order"])

    total = len(lessons)
    done = len([l for l in lessons if l.id in done_ids])

    best = (db.query(SalesQuizAttempt)
            .filter(SalesQuizAttempt.employee_id == user.id)
            .order_by(SalesQuizAttempt.score.desc(), SalesQuizAttempt.attempted_at.desc())
            .first())
    q_total = db.query(SalesQuizQuestion).filter(SalesQuizQuestion.active == True).count()  # noqa: E712
    best_json = None
    if best:
        pct = round(best.score * 100 / best.total) if best.total else 0
        best_json = {"score": best.score, "total": best.total, "pct": pct,
                     "passed": pct >= PASS_PCT, "attempted_at": best.attempted_at.isoformat()}

    return {"tracks": tracks, "total": total, "done": done,
            "quiz_count": q_total, "pass_pct": PASS_PCT, "best": best_json,
            "name": getattr(user, "name", "")}


# ------------------------------------------------------------------ lesson
@router.get("/api/lesson/{lid}")
def api_lesson(lid: int, user: Employee = Depends(get_current_user),
               db: Session = Depends(get_db)):
    ls = db.get(SalesLesson, lid)
    if not ls or not ls.active:
        raise HTTPException(404, "Lesson not found")
    done = db.query(SalesLessonProgress).filter(
        SalesLessonProgress.employee_id == user.id,
        SalesLessonProgress.lesson_id == lid).first() is not None
    return {"id": ls.id, "title": ls.title, "track": ls.track, "summary": ls.summary,
            "body": ls.body, "est_minutes": ls.est_minutes, "level": ls.level, "done": done}


@router.post("/api/lesson/{lid}/complete")
def api_complete(lid: int, user: Employee = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    ls = db.get(SalesLesson, lid)
    if not ls:
        raise HTTPException(404, "Lesson not found")
    row = db.query(SalesLessonProgress).filter(
        SalesLessonProgress.employee_id == user.id,
        SalesLessonProgress.lesson_id == lid).first()
    if not row:
        db.add(SalesLessonProgress(employee_id=user.id, lesson_id=lid,
                                   completed_at=datetime.utcnow()))
        db.commit()
    return {"ok": True}


@router.post("/api/lesson/{lid}/uncomplete")
def api_uncomplete(lid: int, user: Employee = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    row = db.query(SalesLessonProgress).filter(
        SalesLessonProgress.employee_id == user.id,
        SalesLessonProgress.lesson_id == lid).first()
    if row:
        db.delete(row)
        db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ quiz
@router.get("/api/quiz")
def api_quiz(user: Employee = Depends(get_current_user),
             db: Session = Depends(get_db)):
    """Questions WITHOUT the correct answer — graded server-side on submit."""
    qs = (db.query(SalesQuizQuestion).filter(SalesQuizQuestion.active == True)  # noqa: E712
          .order_by(SalesQuizQuestion.sort_order).all())
    return {"questions": [{"code": q.code, "question": q.question,
                           "options": q.options or []} for q in qs],
            "pass_pct": PASS_PCT}


class QuizIn(BaseModel):
    answers: dict = {}   # {question_code: chosen_option_id}


@router.post("/api/quiz/submit")
def api_quiz_submit(payload: QuizIn, user: Employee = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    qs = (db.query(SalesQuizQuestion).filter(SalesQuizQuestion.active == True)  # noqa: E712
          .order_by(SalesQuizQuestion.sort_order).all())
    answers = payload.answers or {}
    score = 0
    results = []
    for q in qs:
        chosen = answers.get(q.code)
        correct = (chosen is not None and str(chosen) == str(q.correct_id))
        if correct:
            score += 1
        results.append({"code": q.code, "chosen": chosen, "correct_id": q.correct_id,
                        "correct": correct, "explanation": q.explanation})
    total = len(qs)
    pct = round(score * 100 / total) if total else 0
    db.add(SalesQuizAttempt(employee_id=user.id, score=score, total=total,
                            answers=answers, attempted_at=datetime.utcnow()))
    db.commit()
    return {"ok": True, "score": score, "total": total, "pct": pct,
            "passed": pct >= PASS_PCT, "results": results}
