# Данные фазы 07

Фаза использует ежедневный order pipeline с тремя таблицами:

- `users` - одна строка на пользователя;
- `orders` - одна строка на заказ;
- `order_items` - одна товарная строка заказа.

`tiny/` является валидным baseline. Дефекты создаются минимальными мутациями этого
набора внутри fixtures, чтобы каждый тест отвечал за один failure class. `sample/`
генерируется локально и нужен для volume checks и monitoring.

Пересоздать committed tiny:

```bash
uv run --locked python phases/07-reliable-analytics/data/generate_data.py \
  --profile tiny
```

Создать локальный sample:

```bash
uv run --locked python phases/07-reliable-analytics/data/generate_data.py \
  --profile sample
```

Проверить воспроизводимость:

```bash
uv run --locked python phases/07-reliable-analytics/data/generate_data.py --check
```
