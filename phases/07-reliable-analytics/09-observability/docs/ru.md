# Наблюдаемость и мониторинг качества данных

> Мониторинг превращает скрытую деградацию batch в измеримый сигнал, но не исправляет данные автоматически.

**Тип:** Build  
**Треки:** core  
**Пререквизиты:** 07/08  
**Время:** ~75 минут

## Цели обучения

- выпускать структурированный run report и JSONL event;
- контролировать freshness, volume, null и duplicate rates;
- различать `data_failure` и `system_failure`.

## Проблема

Успешный exit code не означает свежие или полные данные. Одновременно отсутствие файла
и stale batch требуют разной реакции: первое является системной проблемой, второе
нарушением качества поставки.

## Концепция

Каждая метрика имеет единицу, наблюдаемое значение, оператор и явный threshold.
Фиксированный clock делает freshness-тест воспроизводимым. Failure class маршрутизирует
инцидент, а stable check ID связывает лог, отчет и alert.

## Соберите это

`outputs/quality_monitor.py` измеряет один orders batch.

```bash
uv run --locked python phases/07-reliable-analytics/09-observability/outputs/quality_monitor.py \
  --data-dir phases/07-reliable-analytics/data/tiny \
  --thresholds phases/07-reliable-analytics/09-observability/outputs/example_thresholds.json \
  --observed-at 2026-06-10T12:00:00+03:00 \
  --output /tmp/monitoring-report.json --log /tmp/run.jsonl
```

## Используйте это

Порог должен отражать SLA или исторически обоснованный диапазон. `min_orders=1` в
учебном примере доказывает механику, но production threshold требует владельца и
процесса пересмотра.

## Сломайте это

Уменьшите freshness threshold до одного часа, поставьте `min_orders=11`, очистите ключ
или повторите order. Затем укажите отсутствующий каталог и сравните failure classes.

## Проверьте это

```bash
uv run --locked python -m unittest discover \
  -s phases/07-reliable-analytics/09-observability/tests
```

## Поставьте результат

Результат: `outputs/quality_monitor.py`, thresholds example, JSON report и одна
структурированная JSONL-запись на запуск.

## Упражнения

1. Добавьте relative volume change к предыдущему успешному batch.
2. Спроектируйте warning threshold отдельно от blocking threshold.
3. Добавьте owner и runbook URL в failed event.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Freshness | Время запуска job | Возраст самого нового доступного бизнес-события |
| Data failure | Любое исключение | Нарушение измеримого контракта данных |
| Structured log | Текст с JSON внутри | Запись с устойчивыми полями для машинной обработки |

## Дополнительное чтение

- [Python logging](https://docs.python.org/3/library/logging.html) — logger, records, handlers и уровни.
- [Logging cookbook](https://docs.python.org/3/howto/logging-cookbook.html) — практические схемы структурированного и многопроцессного logging.
- [Google SRE: Monitoring Distributed Systems](https://sre.google/sre-book/monitoring-distributed-systems/) — принципы полезных сигналов и actionable alerts.
