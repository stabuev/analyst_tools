# Аномалии продуктовых метрик

> Аномалия не становится продуктовым сигналом, пока вы не отсеяли качество данных, состав трафика и календарь изменений.

**Тип:** Build  
**Треки:** product  
**Пререквизиты:** `08-product-analytics/09-guardrails`  
**Время:** ~75 минут

## Цели обучения

- Классифицировать скачки метрик как `data_quality`, `composition`, `calendar_effect` или `product_signal`.
- Проверять freshness, duplicate IDs, late arrivals, unknown events и tracking completeness до продуктовой интерпретации.
- Связывать guardrail breaches с decomposition сегментов и релизным календарем.
- Не называть скачок causal effect без эксперимента или отдельного причинного дизайна.
- Отдавать handoff, в котором есть действие: чинить данные, разбирать mix shift, смотреть релиз или расследовать продуктовый сигнал.

## Проблема

После guardrail-урока у команды есть тревожная картина: `support_ticket_rate_7d`, `subscription_cancel_rate_14d` и `refund_rate_7d` breached. Возникает соблазн сразу написать: "новый onboarding и paywall ухудшили пользовательский опыт".

Это слишком быстрый вывод. Скачок метрики может быть настоящим продуктовым сигналом, но может быть и следствием:

- задержки событий или неполной загрузки;
- дубликатов `event_id`;
- нового события вне tracking plan;
- пропавшего обязательного события;
- изменения состава пользователей;
- релиза, который совпал с периодом сравнения.

В рабочей аналитике самая дорогая ошибка часто не в том, что вы не заметили всплеск. Дорогая ошибка в том, что вы заметили всплеск и назвали его причиной, не проверив измерительную систему.

В этом уроке мы строим CLI-детектор аномалий. Он не прогнозирует будущие значения. Он делает более приземленную и полезную вещь: решает, какой тип объяснения разрешен для наблюдаемого скачка прямо сейчас.

## Концепция

Детектор использует четыре класса.

`data_quality` означает, что продуктовую интерпретацию надо остановить. Если есть duplicate IDs, late arrivals сверх политики, stale stream, unknown event names или пропавшие required events, вывод должен быть "сначала чинить измерение".

`composition` означает, что часть изменения объясняется составом аудитории. Например, Android-доля в comparison изменилась, а Android-сегмент дал отрицательный вклад в общий activation delta. Это еще не продуктовая причина; это указатель, что сравнение периодов смешивает поведение и mix shift.

`calendar_effect` означает совпадение с релизом или операционным событием. Такой кандидат не доказывает причинность, но задает следующий шаг: проверить release notes, rollout, платформу, версию приложения и поддержку.

`product_signal` означает, что quality gates прошли, guardrail breached и величина delta достаточно велика по заранее объявленному порогу. Даже тогда это не causal claim. Это разрешение расследовать продуктовую гипотезу без маскировки проблем данных.

Важное правило урока:

```text
product_signal можно выпускать только после quality gates.
```

Если gates не прошли, детектор возвращает только `data_quality` candidates. Он не добавляет рядом "но, возможно, это продукт" как равноправный вывод, потому что такой отчет обычно читают как разрешение действовать.

## Соберите это

Артефакт урока находится в `outputs/anomaly_detector.py`. Он читает:

- `data/tiny/users.csv` - пользователи и test-user флаг;
- `data/tiny/events.csv` - событийный лог продукта;
- `02-event-model/outputs/tracking_plan.json` - допустимые события;
- `data/tiny/release_calendar.csv` - календарь релизов;
- `08-segmentation/outputs/segments.csv` - decomposition по сегментам;
- `09-guardrails/outputs/guardrails.csv` - breached/watch/ok guardrails;
- `outputs/anomaly_spec.json` - periods, gates, thresholds и allowed classifications.

Запустите детектор из корня репозитория:

```bash
python3 phases/08-product-analytics/10-anomalies/outputs/anomaly_detector.py \
  --users phases/08-product-analytics/data/tiny/users.csv \
  --events phases/08-product-analytics/data/tiny/events.csv \
  --tracking-plan phases/08-product-analytics/02-event-model/outputs/tracking_plan.json \
  --release-calendar phases/08-product-analytics/data/tiny/release_calendar.csv \
  --segments phases/08-product-analytics/08-segmentation/outputs/segments.csv \
  --guardrails phases/08-product-analytics/09-guardrails/outputs/guardrails.csv \
  --spec phases/08-product-analytics/10-anomalies/outputs/anomaly_spec.json \
  --output phases/08-product-analytics/10-anomalies/outputs/anomalies.json \
  --report /tmp/anomalies-report.json
```

Quality gates в спецификации:

```json
{
  "max_late_minutes": 1440,
  "min_events_per_period": 1,
  "required_event_names": [
    "account_created",
    "feature_value_seen",
    "support_ticket_created",
    "subscription_cancelled",
    "order_paid"
  ],
  "freshness_max_lag_days": 0
}
```

Thresholds:

```json
{
  "guardrail_delta": 0.15,
  "composition_effect": 0.05,
  "release_window_days": 0
}
```

Эти числа специально маленькие для tiny-data. В реальном продукте они должны быть частью metric review, а не подбираться после просмотра графика.

## Используйте это

Готовый `outputs/anomalies.json` содержит:

- `quality_gates_passed`;
- `summary.by_classification`;
- список `quality_gates`;
- список `candidates`.

На tiny-данных gates проходят, поэтому детектор выпускает 5 кандидатов:

```text
product_signal   guardrail-support_ticket_rate_7d
product_signal   guardrail-subscription_cancel_rate_14d
product_signal   guardrail-refund_rate_7d
composition      composition-platform-android
calendar_effect  calendar-R002-android
```

Это не пять независимых причин. Это диагностическая карта:

- guardrails говорят, что риск действительно вырос;
- Android decomposition говорит, что часть ухудшения связана с сегментным вкладом;
- релиз `R002` на Android совпал с comparison-периодом;
- следующий шаг - расследовать продуктовый сигнал до продолжения rollout.

Запустите пример:

```bash
python3 phases/08-product-analytics/10-anomalies/code/main.py
```

Он печатает компактный summary: валидность, class counts, product-signal IDs, context IDs и recommended action.

## Сломайте это

Попробуйте пять поломок.

1. Продублируйте строку с `event_id=E031`. Детектор вернет `data-quality-event_ids_unique`, запретит `product_signal` и завершит CLI с ненулевым кодом.
2. Переименуйте `signup_started` в `signup_started_v2`. Событие окажется вне tracking plan, gate `known_event_names` упадет.
3. Удалите `support_ticket_created`. Gate `required_events_present` покажет, что обязательный сигнал поддержки отсутствует.
4. Сделайте `received_at` раньше `occurred_at`. Gate `received_after_occurred` заблокирует интерпретацию.
5. Поставьте `observation_end_date` в `2026-06-10`. Последний received event в данных - `2026-06-09`, поэтому freshness gate упадет.

Обратите внимание на поведение: при любой такой поломке детектор не сохраняет guardrail-candidates как `product_signal`. Это намеренное ограничение. Иначе отчет смешал бы "данные грязные" и "продукт сломан" в один список равноправных действий.

## Проверьте это

Запустите тесты урока:

```bash
cd phases/08-product-analytics/10-anomalies
python3 -m unittest discover -s tests -v
```

Тесты проверяют:

- эталонные tiny-данные дают 5 candidates и ожидаемые class counts;
- `outputs/anomalies.json` совпадает с расчетом;
- duplicate `event_id` блокирует product signal;
- unknown event name блокирует product signal;
- отсутствие required event ловится как tracking completeness failure;
- late event сверх политики блокирует вывод;
- freshness зависит от `observation_end_date`;
- `received_at < occurred_at` считается ошибкой качества;
- высокий `min_events_per_period` ломает volume gate;
- высокий `guardrail_delta` убирает product-signal candidates;
- высокий `composition_effect` убирает composition candidate;
- удаление релиза `R002` убирает calendar-effect candidate;
- CLI пишет output и возвращает ненулевой код, если gates fail.

## Поставьте результат

Готовый результат урока:

- `outputs/anomaly_spec.json` - контракт periods, gates, thresholds и allowed classifications;
- `outputs/anomaly_detector.py` - CLI-детектор;
- `outputs/anomalies.json` - именованный артефакт с quality gates и candidates;
- `outputs/artifact.json` - описание артефакта для индекса курса;
- `tests/test_main.py` - behavioral tests.

Безопасный handoff:

```text
Quality gates прошли: duplicate IDs, late arrivals, freshness и tracking completeness
не блокируют интерпретацию. Детектор нашел 3 product_signal candidates по breached
guardrails, 1 composition candidate по Android mix и 1 calendar_effect candidate по
релизу R002. Рекомендация: не продолжать rollout автоматически; расследовать support,
cancellations и refunds вместе с Android release notes и сегментным вкладом.
```

Небезопасный handoff:

```text
Релиз R002 вызвал рост жалоб и возвратов.
```

Второй текст запрещен: календарное совпадение и сегментный вклад еще не доказывают причинность.

## Упражнения

1. Поднимите `guardrail_delta` до `0.6` и объясните, почему `product_signal` исчезает, а `composition-platform-android` остается.
2. Поднимите `composition_effect` до `0.2` и объясните, почему decomposition больше не считается сильным кандидатом.
3. Удалите `R002` из release calendar и сформулируйте handoff без calendar-effect candidate.
4. Добавьте новое обязательное событие в `required_event_names`, которого нет в логе, и объясните, почему это tracking completeness failure.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Аномалия | "Любой скачок уже является продуктовой причиной" | Наблюдаемое отклонение, которому еще нужно присвоить класс объяснения |
| Data quality gate | "Предупреждение рядом с выводом" | Блокер продуктовой интерпретации, если измерительная система не прошла проверку |
| Product signal | "Доказанный эффект релиза" | Кандидат на продуктовую проблему после прохождения quality gates и порогов |
| Composition effect | "Сегмент точно причина" | Часть изменения, связанная с изменением состава аудитории или вклада сегмента |
| Calendar effect | "Релиз вызвал скачок" | Совпадение с релизом или операционным событием, которое задает направление расследования |
| Freshness | "Если данных нет, значит события не произошли" | Проверка, что поток данных догнал observation end и не делает период искусственно пустым |

## Дополнительное чтение

- [Datadog Anomaly Monitor](https://docs.datadoghq.com/monitors/types/anomaly/) - посмотрите, как monitoring-системы отделяют detection от alerting policy и требуют явных параметров окна.
- [Google Cloud Monitoring: alerting policies](https://docs.cloud.google.com/monitoring/alerts/using-alerting-ui) - полезно для мышления про incidents: anomaly должна вести к действию, а не только к красивому графику.
- [Prometheus Alerting Philosophy](https://prometheus.io/docs/practices/alerting/) - короткая официальная памятка о том, почему alerts должны быть симптомными и actionable.
- [Numenta Anomaly Benchmark](https://arxiv.org/abs/1510.03336) - первичный источник про оценку anomaly detection: важно находить отклонения быстро, но не плодить ложные тревоги.
- [Урок про guardrails](../../09-guardrails/docs/ru.md) - вернитесь к breached/watch/ok статусам, потому что anomaly detector использует их как вход.
