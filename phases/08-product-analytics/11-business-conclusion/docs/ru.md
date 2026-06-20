# Бизнес-вывод и рекомендация

> Хороший продуктовый вывод не просит верить аналитику: он показывает решение, доказательства, ограничения и следующий шаг в одной поставке.

**Тип:** Case  
**Треки:** product  
**Пререквизиты:** `08-product-analytics/10-anomalies`  
**Время:** ~105 минут

## Цели обучения

- Собрать результаты продуктовой фазы в единый `product-problem-investigation` package.
- Связать каждый claim с `metric_id`, artifact path и ограничением интерпретации.
- Выбрать решение из ограниченного набора: `continue`, `rollback`, `investigate`, `run_experiment`.
- Не превращать наблюдательную диагностику в causal claim.
- Поставить отчет, recommendation и checksum manifest так, чтобы коллега мог проверить вывод без чтения всего урока.

## Проблема

Фаза 08 дала много артефактов: дерево метрик, tracking plan, activity, funnels, cohorts, retention, monetization, segmentation, guardrails и anomalies. Каждый отдельный файл полезен, но бизнес не принимает решение по каталогу файлов.

Команде нужен ответ:

```text
После изменения onboarding и paywall видим рост ранней активации,
но жалобы и отмены подписки растут. Продолжать rollout, откатить
изменение или поставить следующий проверяемый шаг?
```

Плохой финал фазы звучит так:

```text
Метрики неоднозначные, надо еще посмотреть.
```

В нем нет решения, нет карты доказательств, нет цены ошибки, нет владельца следующего шага. Еще хуже, если отчет делает причинное утверждение: "релиз R002 вызвал рост жалоб". В фазе 08 у нас наблюдательные данные и диагностические checks, а не эксперимент и не causal design.

В этом уроке мы собираем воспроизводимую поставку `product-problem-investigation/`. Она превращает разрозненные расчеты в решение `investigate`, потому что quality gates прошли, guardrails breached, anomalies дают product-signal candidates, но календарь релиза и composition остаются контекстом, а не доказательством причины.

## Концепция

Финальный вывод держится на трех слоях.

**Decision boundary.** До анализа нужно знать допустимые варианты: `continue`, `rollback`, `investigate`, `run_experiment`. Если в отчете может появиться любое слово, решение становится политическим, а не аналитическим.

**Evidence map.** Каждый claim должен отвечать на четыре вопроса:

- что утверждаем;
- какие `metric_id` затронуты;
- где лежит расчет;
- какое ограничение нельзя забывать.

**Recommendation contract.** Машинный `recommendation.json` важен не меньше Markdown-отчета. Он позволяет тестировать, что решение допустимо, claim процитирован, artifact exists, metric IDs резолвятся, а causal wording запрещен без эксперимента.

Формула финального урока:

```text
metric artifacts -> claims with limitations -> decision -> next steps -> manifest
```

Если claim нельзя связать с файлом, он не попадает в recommendation. Если claim нельзя ограничить, он слишком сильный для текущих данных.

## Соберите это

Артефакт урока - `outputs/product_problem_builder.py`. Он собирает пакет:

```text
product-problem-investigation/
├── brief.md
├── metric-tree.json
├── tracking-plan.json
├── metric-specs.json
├── audits/
│   ├── event-quality.json
│   └── metric-quality.json
├── metrics/
│   ├── activity.csv
│   ├── funnel.csv
│   ├── cohorts.csv
│   ├── retention.csv
│   ├── monetization.csv
│   ├── segments.csv
│   ├── guardrails.csv
│   └── anomalies.json
├── figures/
│   ├── metric-trend.png
│   └── segment-decomposition.png
├── report.md
├── recommendation.json
└── manifest.json
```

Запуск из корня репозитория:

```bash
uv run --locked python phases/08-product-analytics/11-business-conclusion/outputs/product_problem_builder.py \
  --phase-root phases/08-product-analytics \
  --output phases/08-product-analytics/11-business-conclusion/outputs/product-problem-investigation
```

Builder делает пять вещей.

1. Копирует канонические артефакты `08/01`-`08/10` в delivery package.
2. Строит два статических PNG: guardrail rates baseline/comparison и platform decomposition.
3. Создает `recommendation.json` с decision, options, claims и next steps.
4. Создает `report.md` с executive summary, evidence map и ограничениями.
5. Считает `manifest.json` с SHA-256 каждого файла.

## Используйте это

Откройте `outputs/product-problem-investigation/recommendation.json`.

Ключевой фрагмент:

```json
{
  "decision": "investigate",
  "allowed_decisions": ["continue", "rollback", "investigate", "run_experiment"],
  "causal_claims_allowed": false
}
```

Почему не `continue`: все три guardrails breached.

Почему не сразу `rollback`: diagnostics are observational. Calendar-effect candidate `R002` задает направление расследования, но не доказывает причину.

Почему не сразу `run_experiment`: сначала нужно проверить Android release context, support reasons, cancellations и refunds, чтобы не запускать эксперимент поверх неразобранного продуктового или instrumentation-риска.

Безопасный вывод:

```text
Рекомендация: investigate before continuing rollout. Quality gates прошли, но
support_ticket_rate_7d, subscription_cancel_rate_14d и refund_rate_7d breached.
Anomaly detector выпустил 3 product_signal candidates, а также composition и
calendar-effect context. Следующий шаг - разобрать Android paywall release,
support tickets, cancellations и refunds; causal claim о релизе не формулируем.
```

Проверьте пример:

```bash
uv run --locked python phases/08-product-analytics/11-business-conclusion/code/main.py
```

Он собирает пакет во временную папку и печатает decision, claims, next steps и число файлов в manifest.

## Сломайте это

Попробуйте четыре поломки.

1. В `recommendation.json` замените decision на `ship_anyway`. Check `decision_allowed` должен упасть.
2. Уберите `artifact_paths` у claim. Check `claims_are_cited` должен упасть.
3. Поставьте claim metric ID `mystery_rate`. Check `claim_metrics_resolve` должен упасть.
4. Напишите `Release R002 caused the support spike`. Check `no_unsupported_causal_claims` должен упасть.

Эти проверки защищают отчет от типичной аналитической эрозии: сначала аккуратно пишем "связано с", потом в слайде для руководителя это превращается в "вызвало". Финальный артефакт должен ловить такой сдвиг.

## Проверьте это

Запустите тесты урока:

```bash
cd phases/08-product-analytics/11-business-conclusion
uv run --locked python -m unittest discover -s tests -v
```

Тесты проверяют:

- package содержит все обязательные файлы;
- manifest hashes совпадают с реальными файлами;
- эталонный `recommendation.json` и `report.md` воспроизводятся builder'ом;
- decision равен `investigate`, а option `investigate` имеет статус `recommended`;
- каждый claim ссылается на существующий artifact и известный `metric_id`;
- causal wording блокируется без causal design;
- uncited claim, unknown metric и invalid decision отклоняются;
- event-quality audit зеркалит anomaly quality gates;
- metric-quality audit требует все файлы поставки;
- скопированные metric artifacts byte-identical исходным outputs;
- figures являются PNG;
- CLI строит пакет и печатает machine-readable report;
- missing source artifact падает до публикации неполной поставки.

## Поставьте результат

Готовый результат урока:

- `outputs/product_problem_builder.py` - CLI-builder поставки;
- `outputs/product-problem-investigation/brief.md` - вопрос и граница решения;
- `outputs/product-problem-investigation/report.md` - бизнес-вывод;
- `outputs/product-problem-investigation/recommendation.json` - machine-readable recommendation;
- `outputs/product-problem-investigation/manifest.json` - SHA-256 manifest;
- `tests/test_main.py` - behavioral tests.

Handoff для коллеги:

```text
Фаза 08 собрана в product-problem-investigation package. Рекомендация:
investigate before continuing rollout. Автоматическое продолжение rollout
отклонено из-за breached guardrails. Rollback пока не выбран, потому что
наблюдательные данные и calendar match не доказывают причинность. Следующие
шаги: Android paywall release context, support/cancel/refund разбор, затем
эксперимент или rollout holdout при чистом instrumentation.
```

## Упражнения

1. Добавьте новый claim в `recommendation.json` и заставьте тесты пройти: укажите `metric_ids`, `artifact_paths` и limitation.
2. Измените thresholds в `08/10` так, чтобы product-signal candidates исчезли, пересоберите package и объясните, почему decision может измениться.
3. Добавьте новый файл в package и обновите manifest через builder, а не вручную.
4. Напишите отдельный тест, который запрещает слово `rollback` в recommendation без claim, поддерживающего этот вариант.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Business conclusion | "Красивый абзац в конце отчета" | Проверяемая связка решения, доказательств, ограничений и следующего действия |
| Evidence map | "Список графиков" | Таблица claim -> artifact -> metric_id -> limitation |
| Recommendation contract | "Формальность для JSON" | Машинный договор, который позволяет тестировать decision и claims |
| Decision boundary | "Решение появится после анализа" | Заранее ограниченный набор допустимых вариантов действия |
| Limitation | "Оговорка для осторожности" | Условие, без которого claim становится сильнее данных |
| Manifest | "Технический хвост" | Контроль воспроизводимости: какие файлы поставлены и какие у них checksums |

## Дополнительное чтение

- [Google Research: HEART framework](https://research.google/pubs/measuring-the-user-experience-on-a-large-scale-user-centered-metrics-for-web-applications/) - первичный источник о том, как связывать продуктовые цели, пользовательские метрики и решения.
- [Atlassian DACI Decision-Making Framework](https://www.atlassian.com/team-playbook/plays/daci) - практический шаблон для разделения driver, approver, contributors и informed в продуктовых решениях.
- [Documenting Architecture Decisions](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions) - полезная аналогия для recommendation: фиксируйте context, decision и consequences, а не только результат.
- [Урок про guardrails](../../09-guardrails/docs/ru.md) - вернитесь к decision status и risk direction, если recommendation кажется слишком строгой.
- [Урок про аномалии](../../10-anomalies/docs/ru.md) - повторите, почему product_signal не равен causal claim.
