# Интеграционный quality gate

> Проверенный результат становится текущим только после успешной атомарной публикации.

**Тип:** Case  
**Треки:** core  
**Пререквизиты:** 07/09  
**Время:** ~105 минут

## Цели обучения

- собрать config, invariant, schema, SQL, golden и monitoring gates;
- публиковать immutable version и checksum manifest;
- доказывать, что failed run не меняет `current.json`.

## Проблема

Даже хорошие отдельные проверки бесполезны, если витрина публикуется раньше их
завершения. Сбой между записью parquet и обновлением метаданных может оставить
потребителю смешанное состояние.

## Концепция

Pipeline сначала валидирует конфигурацию, затем пишет все результаты в staging.
После успешных gates создаются mart, run report и manifest. Каталог staging атомарно
становится immutable version, после чего временный pointer заменяет `current.json`.
Failed runs уходят в отдельный каталог и никогда не меняют pointer.

## Соберите это

`outputs/reliable_order_pipeline.py` переиспользует артефакты всей фазы:

```bash
uv run --locked python phases/07-reliable-analytics/10-quality-gates/outputs/reliable_order_pipeline.py \
  --config phases/07-reliable-analytics/10-quality-gates/outputs/example_config.json \
  --observed-at 2026-06-10T12:00:00+03:00
```

Поставка содержит `orders.parquet`, `daily_metrics.csv`, пять quality reports,
`run.jsonl`, `run-report.json`, `manifest.json` и корневой `current.json`.

## Используйте это

Потребитель сначала читает `current.json`, затем конкретный immutable version. Manifest
позволяет проверить bytes и SHA-256. Stable run ID связывает файлы, логи и отчеты.

## Сломайте это

Измените item total на копейку и убедитесь, что schema/SQL gates падают. Затем запустите
`--simulate-publish-failure`: все файлы будут подготовлены, но прежний pointer останется
byte-identical.

## Проверьте это

```bash
uv run --locked python -m unittest discover \
  -s phases/07-reliable-analytics/10-quality-gates/tests
```

Integration tests проверяют полный набор файлов, parquet grain, data failure,
configuration failure, simulated publication failure и CLI.

## Поставьте результат

Итог фазы: `outputs/reliable_order_pipeline.py`. Это standalone CLI надежной поставки
order mart с доказуемыми gates и атомарным publish contract.

## Упражнения

1. Добавьте проверку manifest на стороне consumer.
2. Реализуйте retention policy, не удаляющую current version.
3. Добавьте warning-only gate и отразите его в run status.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Quality gate | Отчет после публикации | Блокирующее условие до изменения доступного результата |
| Immutable version | Файл, который обычно не меняют | Адресуемая версия, не перезаписываемая после публикации |
| Atomic publish | Быстрая запись всех файлов | Неделимая смена pointer после подготовки согласованной версии |

## Дополнительное чтение

- [Python os.replace](https://docs.python.org/3/library/os.html#os.replace) — атомарная замена пути на одном filesystem.
- [Python hashlib](https://docs.python.org/3/library/hashlib.html) — вычисление SHA-256 для manifest.
- [pandas Parquet IO](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.to_parquet.html) — запись типизированного табличного артефакта.
