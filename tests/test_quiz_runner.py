from __future__ import annotations

import io
import random
import sys
from pathlib import Path
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from course_model import load_curriculum  # noqa: E402
from run_quiz import (  # noqa: E402
    load_questions,
    parse_answer,
    resolve_phase,
    run_attempt,
    select_questions,
    shuffle_options,
)


class QuizRunnerTest(TestCase):
    def test_resolves_phase_by_number_slug_and_title(self) -> None:
        curriculum = load_curriculum()
        expected = curriculum["phases"][3]
        self.assertEqual(resolve_phase("3", curriculum), expected)
        self.assertEqual(resolve_phase("pandas", curriculum), expected)
        self.assertEqual(resolve_phase("pandas и табличные данные", curriculum), expected)

    def test_loads_only_requested_stage(self) -> None:
        phase = load_curriculum()["phases"][3]
        questions = load_questions(phase, stage="post")
        self.assertGreaterEqual(len(questions), 33)
        self.assertTrue(all(question.stage == "post" for question in questions))

    def test_selection_covers_distinct_lessons_before_repeats(self) -> None:
        phase = load_curriculum()["phases"][3]
        questions = load_questions(phase, stage="post")
        selected = select_questions(questions, limit=8, rng=random.Random(7))
        self.assertEqual(len(selected), 8)
        self.assertEqual(len({question.lesson_path for question in selected}), 8)

    def test_option_shuffle_preserves_correct_answer(self) -> None:
        phase = load_curriculum()["phases"][18]
        source = load_questions(phase, stage="post")[0]
        presented = shuffle_options(source, random.Random(11))
        self.assertEqual(
            presented.options[presented.correct],
            source.options[source.correct],
        )

    def test_attempt_delays_feedback_until_rendering(self) -> None:
        phase = load_curriculum()["phases"][0]
        source = load_questions(phase, stage="pre")[:2]
        presented = [shuffle_options(item, random.Random(4)) for item in source]
        output = io.StringIO()
        report = run_attempt(
            presented,
            answers=[item.correct for item in presented],
            output=output,
        )
        self.assertEqual(report["score"], 2)
        self.assertEqual(output.getvalue(), "")
        self.assertTrue(all(item["correct"] for item in report["results"]))

    def test_answer_parser_rejects_invalid_choice(self) -> None:
        self.assertEqual(parse_answer("1", 4), 0)
        self.assertEqual(parse_answer("4", 4), 3)
        with self.assertRaisesRegex(ValueError, "от 1 до 4"):
            parse_answer("5", 4)
        with self.assertRaisesRegex(ValueError, "номер"):
            parse_answer("first", 4)
