"""Validate a course-style technical and business quiz and render it offline."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from string import Template
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

_TEMPLATES = Path(__file__).with_name("templates")
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]


class Bilingual(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    pt: Text
    en: Text


class QuizQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    level: Annotated[int, Field(ge=1, le=4)]
    category: Literal["technical", "business"]
    stem: Bilingual
    options: Annotated[list[Bilingual], Field(min_length=3, max_length=3)]
    correct: Annotated[int, Field(ge=0, le=2)]
    why: Bilingual
    source: Text

    @model_validator(mode="after")
    def distinct_options(self):
        if any(len({getattr(option, lang).casefold() for option in self.options}) != 3 for lang in ("pt", "en")):
            raise ValueError("Each language needs three distinct quiz options.")
        return self


class QuizSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: Bilingual
    questions: Annotated[list[QuizQuestion], Field(min_length=12, max_length=12)]

    @model_validator(mode="after")
    def match_course_levels(self):
        for level in range(1, 5):
            group = [question for question in self.questions if question.level == level]
            if len(group) != 3 or {question.category for question in group} != {"technical", "business"}:
                raise ValueError("Each of four levels needs three questions covering both categories.")
        return self


def load_quiz(path: Path | None = None) -> QuizSpec:
    return QuizSpec.model_validate_json((path or Path(__file__).with_name("quiz.example.json")).read_bytes())


def render_quiz(run: dict, spec: QuizSpec):
    data = json.dumps(spec.model_dump(), ensure_ascii=False).replace("<", "\\u003c")
    template = Template((_TEMPLATES / "quiz.html").read_text(encoding="utf-8"))
    return template.substitute(
        css=(_TEMPLATES / "pilot.css").read_text(encoding="utf-8"),
        quiz_css=(_TEMPLATES / "quiz.css").read_text(encoding="utf-8"),
        script=(_TEMPLATES / "quiz.js").read_text(encoding="utf-8"),
        data=data, title=escape(spec.title.pt), invocation=escape(run["invocation_id"]),
    )
