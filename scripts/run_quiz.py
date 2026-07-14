from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from course_model import ROOT, lesson_dir_name, load_curriculum, phase_dir_name


@dataclass(frozen=True)
class QuizQuestion:
    lesson_path: str
    lesson_title: str
    question_id: str
    stage: str
    prompt: str
    options: tuple[str, ...]
    correct: int
    explanation: str


@dataclass(frozen=True)
class PresentedQuestion:
    source: QuizQuestion
    options: tuple[str, ...]
    correct: int


def resolve_phase(value: str, curriculum: dict[str, Any]) -> dict[str, Any]:
    normalized = value.strip().lower()
    for phase in curriculum["phases"]:
        candidates = {
            str(phase["number"]),
            f"{phase['number']:02d}",
            phase["slug"].lower(),
            phase["title"].lower(),
            f"{phase['number']:02d}-{phase['slug']}".lower(),
        }
        if normalized in candidates:
            return phase
    raise ValueError(f"Не найдена фаза: {value}")


def load_questions(
    phase: dict[str, Any],
    *,
    stage: str,
    root: Path = ROOT,
) -> list[QuizQuestion]:
    phase_directory = phase_dir_name(phase)
    questions: list[QuizQuestion] = []
    for index, lesson in enumerate(phase["lessons"], start=1):
        lesson_directory = lesson_dir_name(index, lesson)
        relative = f"phases/{phase_directory}/{lesson_directory}"
        quiz_path = root / relative / "quiz.json"
        if not quiz_path.is_file():
            continue
        payload = json.loads(quiz_path.read_text(encoding="utf-8"))
        for item in payload["questions"]:
            if stage != "all" and item["stage"] != stage:
                continue
            questions.append(
                QuizQuestion(
                    lesson_path=relative,
                    lesson_title=lesson["title"],
                    question_id=item["id"],
                    stage=item["stage"],
                    prompt=item["question"],
                    options=tuple(item["options"]),
                    correct=item["correct"],
                    explanation=item["explanation"],
                )
            )
    return questions


def select_questions(
    questions: list[QuizQuestion],
    *,
    limit: int,
    rng: random.Random,
) -> list[QuizQuestion]:
    if limit <= 0:
        raise ValueError("limit должен быть положительным")
    if limit >= len(questions):
        selected = list(questions)
        rng.shuffle(selected)
        return selected
    by_lesson: dict[str, list[QuizQuestion]] = {}
    for question in questions:
        by_lesson.setdefault(question.lesson_path, []).append(question)
    lesson_paths = list(by_lesson)
    rng.shuffle(lesson_paths)
    selected: list[QuizQuestion] = []
    for lesson_path in lesson_paths:
        candidates = by_lesson[lesson_path]
        selected.append(rng.choice(candidates))
        if len(selected) == limit:
            return selected
    remaining = [question for question in questions if question not in selected]
    rng.shuffle(remaining)
    return selected + remaining[: limit - len(selected)]


def shuffle_options(question: QuizQuestion, rng: random.Random) -> PresentedQuestion:
    indexed = list(enumerate(question.options))
    rng.shuffle(indexed)
    options = tuple(option for _, option in indexed)
    correct = next(
        position for position, (source_index, _) in enumerate(indexed)
        if source_index == question.correct
    )
    return PresentedQuestion(source=question, options=options, correct=correct)


def parse_answer(value: str, option_count: int) -> int:
    stripped = value.strip()
    if not stripped.isdigit():
        raise ValueError("Введите номер варианта.")
    answer = int(stripped) - 1
    if not 0 <= answer < option_count:
        raise ValueError(f"Введите число от 1 до {option_count}.")
    return answer


def ask(
    question: PresentedQuestion,
    *,
    number: int,
    total: int,
    input_fn: Callable[[str], str] = input,
    output: Any = sys.stdout,
) -> int:
    print(f"\n[{number}/{total}] {question.source.lesson_title}", file=output)
    print(question.source.prompt, file=output)
    for index, option in enumerate(question.options, start=1):
        print(f"  {index}. {option}", file=output)
    while True:
        try:
            return parse_answer(input_fn("Ваш ответ: "), len(question.options))
        except ValueError as error:
            print(error, file=output)


def run_attempt(
    presented: list[PresentedQuestion],
    *,
    answers: list[int] | None = None,
    input_fn: Callable[[str], str] = input,
    output: Any = sys.stdout,
) -> dict[str, Any]:
    if answers is not None and len(answers) != len(presented):
        raise ValueError(
            f"Передано {len(answers)} ответов для {len(presented)} вопросов."
        )
    results: list[dict[str, Any]] = []
    for index, question in enumerate(presented, start=1):
        if answers is None:
            answer = ask(
                question,
                number=index,
                total=len(presented),
                input_fn=input_fn,
                output=output,
            )
        else:
            answer = answers[index - 1]
        is_correct = answer == question.correct
        results.append(
            {
                "lesson_path": question.source.lesson_path,
                "lesson_title": question.source.lesson_title,
                "question_id": question.source.question_id,
                "stage": question.source.stage,
                "question": question.source.prompt,
                "selected_option": question.options[answer],
                "correct_option": question.options[question.correct],
                "correct": is_correct,
                "explanation": question.source.explanation,
            }
        )
    score = sum(item["correct"] for item in results)
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "score": score,
        "total": len(results),
        "results": results,
    }


def render_feedback(report: dict[str, Any], output: Any = sys.stdout) -> None:
    print(f"\nРезультат: {report['score']}/{report['total']}", file=output)
    for index, result in enumerate(report["results"], start=1):
        mark = "✓" if result["correct"] else "✗"
        print(
            f"\n{mark} {index}. {result['lesson_title']}: {result['question']}",
            file=output,
        )
        if not result["correct"]:
            print(f"Ваш ответ: {result['selected_option']}", file=output)
            print(f"Правильный ответ: {result['correct_option']}", file=output)
        print(result["explanation"], file=output)
    print(
        "\nКвиз проверяет узнавание понятий, но не заменяет практику и объяснение решения.",
        file=output,
    )


def parse_answers(value: str, option_count: int = 4) -> list[int]:
    return [parse_answer(item, option_count) for item in value.split(",") if item.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a shuffled self-check quiz for one course phase"
    )
    parser.add_argument("--phase", required=True, help="Phase number, slug or title")
    parser.add_argument("--stage", choices=("pre", "post", "all"), default="post")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--seed", type=int)
    parser.add_argument(
        "--answers",
        help="Comma-separated 1-4 answers for non-interactive checks",
    )
    parser.add_argument("--output", type=Path, help="Write the attempt report as JSON")
    args = parser.parse_args(argv)

    try:
        phase = resolve_phase(args.phase, load_curriculum())
        rng = random.Random(args.seed)
        questions = load_questions(phase, stage=args.stage)
        if not questions:
            raise ValueError("Для выбранной фазы и stage нет вопросов.")
        selected = select_questions(questions, limit=args.limit, rng=rng)
        presented = [shuffle_options(question, rng) for question in selected]
        answers = parse_answers(args.answers) if args.answers is not None else None
        report = run_attempt(presented, answers=answers)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2

    report.update(
        {
            "phase": phase["number"],
            "phase_title": phase["title"],
            "stage": args.stage,
            "seed": args.seed,
        }
    )
    render_feedback(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Отчёт сохранён: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
