# Данные фазы 11

Фаза 11 использует автономный extract подписочного сервиса для локального
analytics engineering проекта. В Git хранится только `tiny` profile: он малый, ручной и
подходит для проверки grain, ключей, source contracts и первых dbt-моделей.

## Профили

- `tiny`: committed baseline для ручной сверки и behavioral tests.
- `sample`: будет добавлен в следующих уроках как детерминированная локальная генерация
  для freshness, incremental windows и docs artifacts.

## Таблицы tiny

| Таблица | Grain | Ключ |
|---|---|---|
| `raw_users` | один зарегистрированный пользователь | `user_id` |
| `raw_events` | одно клиентское или серверное событие | `event_id` |
| `raw_orders` | один заказ или платеж маркетплейса | `order_id` |
| `raw_order_items` | одна строка заказа | `order_id, line_number` |
| `raw_subscriptions` | один период подписки | `subscription_id` |
| `raw_support_tickets` | одно обращение пользователя | `ticket_id` |
| `raw_refunds` | один refund по заказу | `refund_id` |
| `raw_currency_rates` | один курс валюты на дату | `currency, rate_date` |
