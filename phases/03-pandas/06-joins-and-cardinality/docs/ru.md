# Joins, ключи и cardinality

> Join сначала меняет число соответствий между сущностями, а уже потом добавляет столбцы.

**Тип:** Case
**Треки:** Core
**Пререквизиты:** 03/05
**Время:** ~105 минут
**Результат:** валидирует cardinality и не допускает размножения суммы заказа.

## Цели обучения

- Предсказывать one-to-one, one-to-many и many-to-many.
- Использовать `validate` и `indicator`.
- Считать unmatched-ключи.
- Агрегировать detail-таблицу до нужного grain перед join.

## Проблема

`orders` содержит одну строку на заказ, `order_items` — одну строку на позицию. У `O1001`
две позиции. Прямой join повторит `orders.amount=1200` дважды, и последующая сумма станет
завышенной. Все ключи при этом существуют, а merge завершится без исключения.

## Концепция

Cardinality описывает число строк, соответствующих одному ключу с каждой стороны.
`orders -> order_items` является one-to-many. Если результат должен сохранить grain
заказа, позиции сначала агрегируют до одной строки на `order_id`, затем используют
`validate="one_to_one"`.

`indicator=True` добавляет происхождение строки: `both`, `left_only`, `right_only`.
Unmatched-ключи не всегда ошибка, но их число должно быть видимым.

## Соберите это

Выпишите частоты каждого `order_id` слева и справа. Ручное число строк inner join равно
сумме произведений частот по общим ключам. Для `O1001`: `1 * 2 = 2`.

Сначала сложите `quantity * unit_price` по заказу, получите `item_totals` с уникальным
`order_id`, после этого присоединяйте к `orders`.

## Используйте это

```python
item_totals = items.groupby("order_id", as_index=False).agg(
    item_rows=("order_id", "size"),
    item_total=("line_total", "sum"),
)
result = orders.merge(
    item_totals,
    on="order_id",
    how="left",
    validate="one_to_one",
    indicator=True,
)
```

## Сломайте это

Попробуйте `validate="one_to_one"` на сырых позициях: pandas должен отклонить join.
Добавьте дубли в `orders`, отсутствующую позицию и позицию неизвестного заказа. Для каждого
случая зафиксируйте, нарушен ли ключ или появилась unmatched-строка.

## Проверьте это

- Уникальность ключа проверена на стороне, где она ожидается.
- `validate` соответствует предполагаемой cardinality.
- Число строк результата согласовано с целевым grain.
- `left_only` и `right_only` посчитаны.
- Сумма заказа не агрегируется после размножающего join.

## Поставьте результат

`outputs/safe_merge.py` предоставляет общий `safe_merge` и специализированный
`attach_item_totals`. В отчёте сохраняются cardinality, размеры таблиц и unmatched-строки.

## Упражнения

1. Присоедините users к orders с `many_to_one`.
2. Добавьте неизвестный `order_id` в items и объясните политику.
3. Напишите regression test, который ловит завышение общей суммы после наивного join.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Cardinality | Тип join | Число соответствий ключа с каждой стороны |
| Many-to-many | Всегда ошибка API | Часто допустим технически, но опасен для метрик |
| Unmatched key | Обязательно удалить | Наблюдение, требующее явной политики |
| Pre-aggregation | Потеря данных | Приведение detail-таблицы к целевому grain |

## Дополнительное чтение

- [Merge guide](https://pandas.pydata.org/docs/user_guide/merging.html) — изучите типы объединений и ключи.
- [pandas.merge](https://pandas.pydata.org/docs/reference/api/pandas.merge.html) — разберите параметры `validate` и `indicator`.
- [Merge duplicate keys](https://pandas.pydata.org/docs/user_guide/merging.html#merge-key-uniqueness) — прочитайте проверку уникальности ключей.
