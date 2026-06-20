# Golden datasets и regression tests

> Golden baseline фиксирует бизнес-семантику, а не случайное byte-for-byte состояние всего файла.

**Тип:** Case  
**Треки:** core  
**Пререквизиты:** 07/07  
**Время:** ~75 минут

## Цели обучения

- выбирать маленький reviewed baseline;
- нормализовать порядок и числовое представление перед сравнением;
- отличать регрессию от согласованного изменения правила.

## Проблема

Snapshot полного CSV падает из-за порядка строк, timestamp запуска или версии writer.
Если snapshot обновляют одной командой без чтения diff, он перестает защищать бизнес-
логику.

## Концепция

Golden содержит минимальный вход и ожидаемый semantic output: counts, paid revenue,
status partition и дневные метрики. Harness строит output заново, нормализует его и
показывает diff по JSON paths. Обновление golden является review бизнес-изменения.

## Соберите это

Сравните `outputs/orders_golden.json` и функцию `semantic_snapshot`:

```bash
uv run --locked python phases/07-reliable-analytics/08-golden-datasets/outputs/golden_regression.py \
  --data-dir phases/07-reliable-analytics/data/tiny \
  --golden phases/07-reliable-analytics/08-golden-datasets/outputs/orders_golden.json
```

## Используйте это

Смотрите не только `difference_count`, но и пути. Изменение paid policy должно затронуть
paid count/revenue, но не общий order count. Не включайте в golden поля, которые не
несут проверяемой семантики.

## Сломайте это

Сделайте `pending` заказ платным или измените одну сумму на копейку. Harness должен
показать узкий semantic diff. Перестановка строк, напротив, не должна менять snapshot.

## Проверьте это

```bash
uv run --locked python -m unittest discover \
  -s phases/07-reliable-analytics/08-golden-datasets/tests
```

## Поставьте результат

Результат: `outputs/golden_regression.py` и reviewed baseline
`outputs/orders_golden.json`.

## Упражнения

1. Добавьте в golden refunded amount и объясните бизнес-смысл.
2. Исключите новое нестабильное поле `generated_at`.
3. Напишите checklist review для осознанного обновления baseline.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Golden dataset | Большой production snapshot | Маленький reviewed пример с ожидаемой семантикой |
| Semantic diff | Текстовый diff файлов | Различия нормализованных бизнес-полей |
| Regression | Любое изменение output | Неожиданное нарушение ранее подтвержденного поведения |

## Дополнительное чтение

- [Python json](https://docs.python.org/3/library/json.html) — стабильная сериализация структурированного baseline.
- [pandas testing](https://pandas.pydata.org/docs/reference/testing.html) — семантическое сравнение табличных объектов.
- [pytest parametrization](https://docs.pytest.org/en/stable/how-to/parametrize.html) — проверка нескольких reviewed regression cases одним контрактом.
