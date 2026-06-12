---
name: check-understanding
description: Quiz a learner on one course phase using its actual lessons, outcomes, failure modes, and quiz files.
---

# Check Understanding

Use this skill when a learner asks to check, review, or test understanding of a phase.

## Input

Accept a phase number, slug, or title. Resolve it through `curriculum.json`.

## Source Of Truth

Read:

1. The matching `phases/<phase>/README.md`.
2. `docs/ru.md` and `quiz.json` for lessons that exist.
3. Designed outcomes and artifacts in `curriculum.json` when lesson content is not written.

Never claim to test material that is only marked `planned` and has no detailed outcome.

## Procedure

Generate eight questions and present them one at a time:

- two concept questions;
- two questions about failure modes or broken data;
- two code, SQL, table, or calculation questions;
- one verification question;
- one artifact or transfer question.

Prefer existing `post` questions from lesson quizzes, but do not repeat them verbatim when
the learner has already answered them in the current conversation.

After each answer:

1. Mark it correct, partial, or incorrect.
2. Give a concise explanation.
3. Record the lesson or outcome being tested.

Do not reveal later answers.

## Result

At the end, return:

- score out of 16 (`2` correct, `1` partial, `0` incorrect);
- strengths;
- misconceptions and their consequence in real analytical work;
- exact lessons to revisit;
- one practical exercise;
- recommendation: continue, review selected lessons, or repeat the phase.

Passing guidance:

- `14-16`: continue;
- `10-13`: review selected lessons;
- below `10`: repeat the phase.

The learner must demonstrate reasoning. A guessed multiple-choice answer without an
explanation cannot receive full credit on reasoning questions.

