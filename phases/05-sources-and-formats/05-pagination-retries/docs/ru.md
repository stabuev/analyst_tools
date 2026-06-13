# Pagination, timeouts и retries

> Устойчивый клиент умеет закончить работу и ограничивает цену каждого повторения.

**Тип:** Build  
**Треки:** Core  
**Пререквизиты:** 05/04  
**Время:** ~90 минут  
**Результат:** загружает все страницы API с явным условием остановки, ограниченными
retries, backoff и поддержкой Retry-After.

## Цели обучения

- Следовать `next` до документированного окончания.
- Отличать временные ошибки от постоянных.
- Применять bounded exponential backoff и `Retry-After`.
- Обнаруживать циклы pagination и дубликаты ключей.

## Проблема

Первая страница API успешна, вторая временно отвечает 429, а третья завершает выдачу.
Наивный цикл либо теряет страницы, либо повторяет запрос бесконечно. Еще один дефект
сервера возвращает ссылку на уже посещенную страницу.

## Концепция

У клиента четыре независимых ограничения:

| Ограничение | Назначение |
|---|---|
| timeout | ограничить одно ожидание |
| max retries | ограничить число повторов страницы |
| max backoff | ограничить паузу |
| max pages | ограничить ошибочную pagination |

Повторять безопасно временные статусы вроде 429, 502, 503 и 504. Ошибка 400 обычно
описывает постоянный дефект запроса и не исправится ожиданием.

## Соберите это

Минимальный цикл хранит `url`, множество visited и список records. После успешного ответа
он добавляет `items` и присваивает `url = payload["next"]`. Значение `None` завершает
загрузку.

Для повтора без серверной подсказки:

```python
delay = min(backoff_factor * 2**attempt, max_backoff)
```

Если присутствует `Retry-After`, используйте его секунды или HTTP-date в пределах
`max_backoff`.

```bash
uv run --locked python code/main.py
```

## Используйте это

Артефакт применяет один timeout ко всем страницам, закрывает каждый response и записывает
retry events:

```bash
uv run --locked python outputs/paginated_client.py \
  --url https://api.example.org/orders \
  --output-dir delivery \
  --max-pages 100 \
  --max-retries 3
```

Production-адаптер может использовать `urllib3.Retry`, но условие окончания и проверка
grain остаются прикладной логикой.

## Сломайте это

Проверьте:

1. 429 с `Retry-After: 2`;
2. 503 без заголовка;
3. 400, который нельзя повторять;
4. `next`, указывающий на текущую страницу;
5. отсутствие `next=null` до `max_pages`;
6. одинаковый `order_id` на разных страницах.

## Проверьте это

- три страницы дают пять records;
- каждая страница получает timeout;
- `Retry-After` важнее локального backoff;
- backoff ограничен максимумом;
- 400 выполняется один раз;
- цикл обнаруживается до повторного запроса;
- delivery содержит JSONL и report.

```bash
uv run --locked python -m unittest discover -s tests
```

## Поставьте результат

`outputs/paginated_client.py` поставляет records и журнал страниц/retries. Отчет доказывает
условие остановки и позволяет отличить медленный источник от ошибки данных.

## Упражнения

1. Добавьте cursor pagination без URL.
2. Реализуйте jitter и протестируйте его границы.
3. Сохраняйте checkpoint после каждой страницы для безопасного resume.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Pagination | Несколько независимых запросов | Последовательность с договорным переходом и окончанием |
| Retry | Повтор любой ошибки | Ограниченный повтор временного безопасного запроса |
| Backoff | Постоянная пауза | Растущее ожидание между попытками |
| Retry-After | Timeout | Серверная рекомендация времени следующей попытки |
| Retry storm | Быстрый recovery | Синхронные повторы, усиливающие перегрузку |

## Дополнительное чтение

- [urllib3: `Retry`](https://urllib3.readthedocs.io/en/stable/reference/urllib3.util.html#urllib3.util.Retry) — изучите status allowlist, backoff, jitter и `respect_retry_after_header`.
- [Requests: HTTPAdapter](https://requests.readthedocs.io/en/latest/api/#requests.adapters.HTTPAdapter) — разберите подключение retry-policy к Session.
- [RFC 9110: Retry-After](https://www.rfc-editor.org/rfc/rfc9110#field.retry-after) — сравните delay-seconds и HTTP-date.
- [AWS: Exponential Backoff and Jitter](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/) — поймите, почему одинаковый backoff множества клиентов создает пики.
