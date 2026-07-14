<!-- Generated from curriculum.json. Do not edit manually. -->

# Фаза 18: Капстоун-проекты

> Соберите законченное исследование или аналитический продукт выбранного маршрута.

- **Треки:** core, product, data, decision, ml, delivery
- **Пререквизиты:** Фаза 17
- **Время:** ~30-50 часов
- **Итоговый артефакт:** Capstone portfolio package

## Уроки

| № | Урок | Время | Проверяемый результат | Артефакт | Статус |
|---:|---|---:|---|---|---|
| 01 | [Выбор и ограничение задачи](01-problem-selection) | 240 мин | Выбирает capstone-маршрут, формулирует решение и claim type, ограничивает scope и non-goals, проверяет маршрутные пререквизиты и составляет milestone/risk plan. | Capstone brief validator с route readiness, scope audit, risk register и milestone plan | complete |
| 02 | [Контракт и аудит данных](02-data-contract) | 360 мин | Фиксирует dataset manifest, grain, keys, lineage, временные границы, license/privacy policy и маршрутные leakage/quality checks до реализации метода. | Capstone data contract auditor с dataset manifest, grain/key audit, source policy и checksum inventory | complete |
| 03 | [Baseline результата](03-baseline) | 300 мин | Строит простейший decision-relevant baseline выбранного маршрута, выполняет ручную сверку и фиксирует критерий, по которому сложная реализация должна дать практическое улучшение. | Capstone baseline gate с manual cross-check, acceptance metric и complexity budget | complete |
| 04 | [Реализация проекта](04-implementation) | 720 мин | Реализует маршрутный analytical workflow поверх зафиксированных brief, data contract и baseline, сохраняя config, run trace, evidence links и воспроизводимую команду сборки. | Capstone implementation package с route adapter, evidence ledger, run manifest и reproducible build command | complete |
| 05 | [Проверки и независимая валидация](05-verification) | 420 мин | Проверяет проект в чистом окружении, независимо пересчитывает ключевой результат, запускает behavioral и negative tests, sensitivity checks и аудит claim-evidence traceability. | Independent verification harness с clean-room rerun, shadow calculation, failure fixtures и verification report | complete |
| 06 | [Peer review](06-peer-review) | 300 мин | Проводит evidence-based review чужого проекта, классифицирует blockers и improvements, а как автор ведет response ledger и повторно подтверждает исправленные claims и checksums. | Capstone peer-review kit с review rubric, finding ledger, author responses и re-review gate | complete |
| 07 | [Защита решения](07-defense) | 300 мин | Собирает portfolio-ready capstone package, демонстрирует решение и воспроизводимый запуск, отвечает на challenge questions и получает итоговый статус по blockers и общей rubric. | Capstone portfolio package с defense brief, demo script, review closure, decision report и checksum manifest | complete |

## Как проходить фазу

1. Ответьте на входные вопросы до чтения reference implementation.
2. Для каждого урока воспроизведите ручной механизм в локальной папке `work/`.
3. Запустите пример, один failure mode и тесты урока.
4. Выполните хотя бы одно упражнение, которое меняет данные или правило.
5. После фазы пройдите перемешанную самопроверку:

```bash
uv run --locked python scripts/run_quiz.py --phase 18 --stage post --limit 8
```

Кнопка прогресса на сайте является ручной отметкой, а не сертификатом. Критерий освоения — объяснить решение, воспроизвести расчёт и диагностировать хотя бы одну поломку.

## Критерий завершения

Студент ограничивает задачу, фиксирует контракт данных и baseline, реализует проект выбранного маршрута, проходит независимую валидацию, peer review и защищает решение по общей rubric.

[Вернуться к общей дорожной карте](../../ROADMAP.md)
