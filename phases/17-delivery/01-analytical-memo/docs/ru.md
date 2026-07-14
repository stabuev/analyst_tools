# Аналитическая записка для решения

> Хорошая записка не расширяет данные до красивой истории. Она оставляет decision owner с ясным выбором, evidence, ограничениями и следующим действием.

**Тип:** Learn  
**Треки:** delivery  
**Пререквизиты:** `07-reliable-analytics/10-quality-gates`  
**Время:** ~75 минут

## Цели обучения

- Отличать аналитический отчет от decision memo.
- Фиксировать допустимые варианты решения до написания рекомендации.
- Связывать каждый claim с evidence, metric, quality status и limitation.
- Блокировать uncited claims, blocked evidence и causal wording без causal design.
- Поставлять короткую записку вместе с машинным audit и checksum manifest.

## Проблема

К концу анализа у вас обычно есть таблицы, графики, quality gates и несколько осторожных выводов. Но заказчик принимает не таблицу, а решение:

```text
Продолжаем rollout, ставим паузу, откатываем изменение или запускаем эксперимент?
```

Плохая поставка выглядит так:

```text
Метрики выросли, есть риск, нужно дополнительно посмотреть.
```

В ней нет явной рекомендации, не видно допустимых вариантов, непонятно, какие claims поддержаны evidence, а какие появились из общего ощущения. Еще хуже, если аккуратная наблюдательная диагностика в финальном абзаце превращается в overclaim:

```text
Релиз R002 вызвал рост отмен подписки.
```

Такой текст может быть удобным для обсуждения, но он сильнее данных, если у вас не было эксперимента или другого causal design. Decision memo должен помогать действовать и одновременно защищать границу claim.

В этом уроке мы строим `decision-memo-builder`: CLI, который превращает `memo_spec.json`, `evidence.csv` и `quality_gates.csv` в короткую записку, claim-evidence matrix, audit и manifest.

## Концепция

Decision memo держится на пяти элементах.

**Question.** Один вопрос, ради которого пишется записка. Если вопросов три, получится отчет для чтения, а не memo для решения.

**Decision options.** Допустимые варианты действия известны заранее: например, `continue_rollout`, `pause_rollout`, `rollback`, `run_experiment`. Рекомендация вне этого списка не публикуется молча.

**Recommendation.** Один рекомендуемый вариант и короткое объяснение, почему он лучше альтернатив сейчас.

**Evidence boundary.** Каждый claim связан с evidence ID, artifact path, metric ID, quality status и limitation. Claim без evidence не попадает в поставку.

**No-overclaim audit.** Если дизайн наблюдательный, builder запрещает causal/proof wording. Можно писать "связано с", "наблюдается в", "совпадает по календарю"; нельзя писать "вызвало", "доказало", "caused" без соответствующего дизайна.

Формула урока:

```text
memo spec + evidence + quality gates
  -> claim-evidence matrix
  -> executive memo
  -> audit
  -> manifest
```

## Соберите это

Артефакт урока - `outputs/decision_memo_builder.py`. Он принимает три входа.

`memo_spec.json` задает вопрос, audience, owner, варианты решения, рекомендацию, claims, limitations и next steps.

`evidence.csv` задает строки evidence:

```text
evidence_id, artifact_path, metric_id, finding, evidence_type,
quality_status, claim_scope, limitation, freshness
```

`quality_gates.csv` задает проверки качества:

```text
gate_id, gate_name, status, evidence_id, message
```

Запуск с встроенным примером:

```bash
uv run --locked python phases/17-delivery/01-analytical-memo/outputs/decision_memo_builder.py \
  --write-example /tmp/decision-memo-inputs \
  --output-dir /tmp/decision-memo
```

Builder создаст:

```text
/tmp/decision-memo/
├── executive_memo.md
├── claim_evidence_matrix.csv
├── memo_audit.json
└── manifest.json
```

Основные проверки:

1. `decision_is_allowed` - рекомендация входит в заранее заданный список вариантов.
2. `recommended_option_is_marked` - ровно один вариант помечен как recommended.
3. `claims_have_evidence` - у каждого claim есть evidence ID.
4. `claim_evidence_ids_resolve` - evidence ID существует в `evidence.csv`.
5. `supporting_claims_have_usable_evidence` - supporting claim не опирается на blocked evidence.
6. `no_unsupported_overclaim_wording` - наблюдательная записка не делает причинных утверждений.

## Используйте это

Откройте `memo_audit.json`.

В эталонном примере audit остается `valid: true`, но статус равен `ready_with_warnings`. Это нормальная ситуация для осторожной поставки: freshness и duplicate checks прошли, guardrails дают риск, но support reason coverage имеет warning и должен быть виден в limitations.

Ключевой смысл:

```text
Рекомендация: pause_rollout.
Причина: guardrails above threshold, но текущая evidence наблюдательная.
Ограничение: нельзя утверждать, что release R002 вызвал рост отмен.
Следующий шаг: разобрать support/cancel reasons и подготовить rollback или holdout plan.
```

Проверьте демонстрационный запуск:

```bash
uv run --locked python phases/17-delivery/01-analytical-memo/code/main.py
```

Он создаст временные входы, соберет package и напечатает machine-readable summary: valid, readiness status, recommendation, число claims, число строк матрицы и список файлов.

## Сломайте это

Попробуйте четыре поломки.

1. В `memo_spec.json` замените `recommended_decision` на `ship_anyway`. Check `decision_is_allowed` должен упасть.
2. Уберите `evidence_ids` у claim. Check `claims_have_evidence` должен упасть.
3. Замените evidence ID на несуществующий. Check `claim_evidence_ids_resolve` должен упасть.
4. Напишите `Release R002 caused the cancellation increase`. Check `no_unsupported_overclaim_wording` должен упасть.

Эти проверки нужны не для бюрократии. Они ловят момент, когда аккуратный аналитический вывод начинает звучать увереннее, чем позволяют данные.

## Проверьте это

Запустите тесты урока:

```bash
cd phases/17-delivery/01-analytical-memo
uv run --locked python -m unittest discover -s tests -v
```

Тесты проверяют:

- пример собирается в `ready_with_warnings`, но без blockers;
- `claim_evidence_matrix.csv` связывает claims с artifact, metric, quality и limitation;
- uncited claim блокирует audit;
- неизвестный evidence ID блокирует audit;
- blocked supporting evidence запрещает публикацию;
- blocking quality gate запрещает публикацию;
- causal/overclaim wording отклоняется без causal design;
- invalid decision вне allowed options отклоняется;
- rendered memo содержит вопрос, варианты, рекомендацию, evidence, limitations и next step;
- manifest хеширует входы и выходы;
- CLI возвращает machine-readable report;
- режим `--write-example` создает минимальные входы;
- `code/main.py` запускается без внешних файлов.

## Поставьте результат

Готовый результат урока:

- `outputs/decision_memo_builder.py` - CLI-builder decision memo package;
- `executive_memo.md` - короткая записка для decision owner;
- `claim_evidence_matrix.csv` - claim -> evidence -> metric -> quality -> limitation;
- `memo_audit.json` - машинный audit готовности и warnings;
- `manifest.json` - SHA-256 manifest входов и выходов;
- `tests/test_main.py` - behavioral tests для delivery contract.

Handoff для коллеги:

```text
Decision memo собран. Рекомендация: pause_rollout, потому что guardrails above
threshold, но evidence наблюдательная. Audit valid, readiness ready_with_warnings:
support reason coverage раскрыт как warning. Causal claim о релизе не делаем.
Следующий шаг: Support analytics разбирает support/cancel reasons, Growth PM
готовит rollback или holdout plan по результатам разбора.
```

## Упражнения

1. Добавьте четвертый claim про segment risk и свяжите его с новой строкой evidence.
2. Сделайте support reason coverage `block` и объясните, почему memo больше нельзя публиковать.
3. Добавьте отдельный warning для stale dashboard и выведите его в limitations.
4. Расширьте no-overclaim audit русскими формулировками, которые часто встречаются в вашей команде.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Decision memo | "Короткий отчет" | Документ, который помогает выбрать действие и фиксирует evidence, ограничения и next step |
| Claim | "Любая фраза вывода" | Проверяемое утверждение, которое должно иметь evidence и limitation |
| Evidence boundary | "Сноска на источник" | Явная граница: artifact, metric, quality status, scope и limitation |
| Overclaim | "Уверенная формулировка" | Утверждение сильнее данных, например causal wording без causal design |
| Readiness status | "Формальность audit" | Состояние поставки: ready, ready_with_warnings или blocked |
| Decision owner | "Получатель письма" | Человек, который принимает или согласует действие после записки |

## Дополнительное чтение

- [Digital.gov: Plain language guide series](https://digital.gov/guides/plain-language) - официальный набор принципов ясного письма: пишите для конкретной аудитории и проверяйте понимание.
- [Google Technical Writing: Audience](https://developers.google.com/tech-writing/one/audience) - практичный разбор того, как подстраивать документ под роль, контекст и знания читателя.
- [GOV.UK Writing guidelines](https://guidance.publishing.service.gov.uk/writing-to-gov-uk-standards/writing-guidelines/) - пример строгих редакторских стандартов для текстов, которые должны быстро приводить пользователя к действию.
- [Documenting Architecture Decisions](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions) - полезная аналогия для decision memo: context, decision, status и consequences в коротком проверяемом документе.
- [Бизнес-вывод и рекомендация](../../../08-product-analytics/11-business-conclusion/docs/ru.md) - вернитесь к product recommendation contract, если нужно повторить claim -> evidence -> limitation.
