# Данные фазы 06

Фаза использует синтетическую таблицу `user_journeys` о первых семи днях после
регистрации в подписочном сервисе. Grain — одна строка на пользователя и одно окно
наблюдения, но в данных намеренно присутствует повторная доставка одной строки.

- `tiny/` хранится в Git и предназначен для ручных расчетов, behavioral tests и разбора
  каждого известного дефекта.
- `sample/` содержит около 20 тысяч строк, генерируется локально и используется для
  распределений, overplotting, faceting и bootstrap.
- `contract.json` фиксирует grain, типы, nullable policy, дефекты и содержательные
  сигналы.

В данных одновременно присутствуют:

- неполные семидневные окна последних когорт;
- структурный пропуск `app_version` для web;
- дубликат `user_id`, случайный пропуск страны и невозможное отрицательное время;
- heavy-tailed длительность onboarding и сумма первого заказа;
- смена состава каналов после релиза;
- дополнительное ухудшение Android 2.4, которое не объясняется только составом трафика.

Пересоздать committed tiny-набор:

```bash
uv run --locked python phases/06-eda-and-visualization/data/generate_data.py \
  --profile tiny
```

Создать локальный sample-набор:

```bash
uv run --locked python phases/06-eda-and-visualization/data/generate_data.py \
  --profile sample
```

Проверить воспроизводимость committed tiny:

```bash
uv run --locked python phases/06-eda-and-visualization/data/generate_data.py --check
```
