"""Shared engine for the portal's training modules (Sales, Design, …).

A training course is four tables with the same shape — lessons, quiz
questions, per-user lesson progress, per-user quiz attempts. Rather than
duplicate a route + page per course, `build_training_router` wires a full
course from its four model classes and renders the one generic template.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .database import get_db
from .deps import get_current_user
from .models import Employee

templates = Jinja2Templates(directory="app/templates")

DEFAULT_PASS_PCT = 70


class QuizIn(BaseModel):
    answers: dict = {}   # {question_code: chosen_option_id}


def build_training_router(prefix, *, Lesson, Question, Progress, Attempt,
                          page_title, heading, subtitle, pass_pct=DEFAULT_PASS_PCT):
    """Return an APIRouter serving a complete training course at `prefix`."""
    router = APIRouter(prefix=prefix, tags=[prefix.strip("/")])

    @router.get("/", response_class=HTMLResponse)
    def page(request: Request, user: Employee = Depends(get_current_user),
             db: Session = Depends(get_db)):
        return templates.TemplateResponse(request, "training_module.html", {
            "user": user, "api_base": prefix, "page_title": page_title,
            "heading": heading, "subtitle": subtitle})

    @router.get("/api/overview")
    def api_overview(user: Employee = Depends(get_current_user),
                     db: Session = Depends(get_db)):
        lessons = (db.query(Lesson).filter(Lesson.active == True)  # noqa: E712
                   .order_by(Lesson.track_order, Lesson.sort_order).all())
        done_ids = {p.lesson_id for p in db.query(Progress.lesson_id)
                    .filter(Progress.employee_id == user.id).all()}
        tracks, by_track = [], {}
        for ls in lessons:
            t = by_track.get(ls.track)
            if not t:
                t = {"track": ls.track, "track_order": ls.track_order, "lessons": []}
                by_track[ls.track] = t
                tracks.append(t)
            t["lessons"].append({
                "id": ls.id, "code": ls.code, "title": ls.title, "summary": ls.summary,
                "est_minutes": ls.est_minutes, "level": ls.level, "done": ls.id in done_ids})
        tracks.sort(key=lambda x: x["track_order"])
        total = len(lessons)
        done = len([l for l in lessons if l.id in done_ids])
        best = (db.query(Attempt).filter(Attempt.employee_id == user.id)
                .order_by(Attempt.score.desc(), Attempt.attempted_at.desc()).first())
        q_total = db.query(Question).filter(Question.active == True).count()  # noqa: E712
        best_json = None
        if best:
            pct = round(best.score * 100 / best.total) if best.total else 0
            best_json = {"score": best.score, "total": best.total, "pct": pct,
                         "passed": pct >= pass_pct,
                         "attempted_at": best.attempted_at.isoformat()}
        return {"tracks": tracks, "total": total, "done": done,
                "quiz_count": q_total, "pass_pct": pass_pct, "best": best_json,
                "name": getattr(user, "name", "")}

    @router.get("/api/lesson/{lid}")
    def api_lesson(lid: int, user: Employee = Depends(get_current_user),
                   db: Session = Depends(get_db)):
        ls = db.get(Lesson, lid)
        if not ls or not ls.active:
            raise HTTPException(404, "Lesson not found")
        done = db.query(Progress).filter(
            Progress.employee_id == user.id, Progress.lesson_id == lid).first() is not None
        return {"id": ls.id, "title": ls.title, "track": ls.track, "summary": ls.summary,
                "body": ls.body, "est_minutes": ls.est_minutes, "level": ls.level, "done": done}

    @router.post("/api/lesson/{lid}/complete")
    def api_complete(lid: int, user: Employee = Depends(get_current_user),
                     db: Session = Depends(get_db)):
        ls = db.get(Lesson, lid)
        if not ls:
            raise HTTPException(404, "Lesson not found")
        row = db.query(Progress).filter(
            Progress.employee_id == user.id, Progress.lesson_id == lid).first()
        if not row:
            db.add(Progress(employee_id=user.id, lesson_id=lid, completed_at=datetime.utcnow()))
            db.commit()
        return {"ok": True}

    @router.post("/api/lesson/{lid}/uncomplete")
    def api_uncomplete(lid: int, user: Employee = Depends(get_current_user),
                       db: Session = Depends(get_db)):
        row = db.query(Progress).filter(
            Progress.employee_id == user.id, Progress.lesson_id == lid).first()
        if row:
            db.delete(row)
            db.commit()
        return {"ok": True}

    @router.get("/api/quiz")
    def api_quiz(user: Employee = Depends(get_current_user),
                 db: Session = Depends(get_db)):
        qs = (db.query(Question).filter(Question.active == True)  # noqa: E712
              .order_by(Question.sort_order).all())
        return {"questions": [{"code": q.code, "question": q.question,
                               "options": q.options or []} for q in qs],
                "pass_pct": pass_pct}

    @router.post("/api/quiz/submit")
    def api_quiz_submit(payload: QuizIn, user: Employee = Depends(get_current_user),
                        db: Session = Depends(get_db)):
        qs = (db.query(Question).filter(Question.active == True)  # noqa: E712
              .order_by(Question.sort_order).all())
        answers = payload.answers or {}
        score, results = 0, []
        for q in qs:
            chosen = answers.get(q.code)
            correct = (chosen is not None and str(chosen) == str(q.correct_id))
            if correct:
                score += 1
            results.append({"code": q.code, "chosen": chosen, "correct_id": q.correct_id,
                            "correct": correct, "explanation": q.explanation})
        total = len(qs)
        pct = round(score * 100 / total) if total else 0
        db.add(Attempt(employee_id=user.id, score=score, total=total,
                       answers=answers, attempted_at=datetime.utcnow()))
        db.commit()
        return {"ok": True, "score": score, "total": total, "pct": pct,
                "passed": pct >= pass_pct, "results": results}

    return router
