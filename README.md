# Golub4ik (WikiHampter) DeadSpace Checker

<p align="center">
  <img src="DeadSpaceLogo.png" alt="Logo" width="200"/>
</p>

Инструмент для администраторов SS14. Связывает сообщения из Discord с данными панели администратора DeadSpace14, чтобы находить обходы банов по HWID, IP и временным меткам.

---

## Для пользователя

### Быстрый старт

#### Вариант 1 — Скачать EXE (проще всего)

1. Скачай `DeadSpaceChecker.exe` из раздела **Releases**
2. Запусти — программа сама создаст базу данных при первом сканировании

#### Вариант 2 — С готовой базой (первый запуск мгновенно)

Первый сбор данных из Discord занимает 10–15 минут. Чтобы не ждать:

1. Скачай `DeadSpaceChecker.exe` и `deadspace_checker.db` из **Releases**
2. Положи оба файла рядом
3. Запусти `DeadSpaceChecker.exe`

Программа найдёт базу автоматически. При следующих запусках будут докачиваться только новые сообщения — это занимает секунды.

#### Вариант 3 — Из исходников (Python)

```bash
git clone <ссылка_на_репозиторий>
cd Golub4ik-DeadSpace-Check
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m deadspace_checker.gui.app
```

#### Вариант 4 — Собрать базу самому (если в релизе нет готовой)

```bash
pip install -r requirements.txt
python build_cache.py --token ВАШ_DISCORD_ТОКЕН
```

Готовый `deadspace_checker.db` можно использовать самому или загрузить в релиз для других.

### Что нужно для работы

- **Discord токен** — как получить, написано ниже
- **Логин и пароль от админ-панели** DeadSpace14
- **Доступ к каналам Discord**, которые указаны в конфиге

### Как получить Discord токен

1. Открой Discord (десктоп или браузер)
2. Нажми `F12` (или `Ctrl+Shift+I`)
3. Перейди на вкладку **Network**
4. Отправь любое сообщение в чат
5. Найди запрос к `discord.com/api/`
6. В заголовках запроса скопируй значение `authorization` (это и есть твой токен)

> Токен пользовательский (self-bot), не бота. Не делись им ни с кем.

### Интерфейс

Окно программы (`860x780`) выполнено в тёмной «космической» теме с анимированным звёздным фоном. Все настройки вводятся в поля и сохраняются в SQLite.

#### 🔐 Панель доступа (в верхней части окна)

| Поле/Кнопка | Назначение |
|---|---|
| **Администратор** | Логин от аккаунта Space Station 14 (для доступа к админ-панели) |
| **Пароль** | Пароль от SS14. Скрыт звёздочками |
| **Discord токен** | Self-bot токен Discord (см. инструкцию выше). Скрыт звёздочками. Кнопка `?` — подсказка как получить токен |
| **Auth cookie (опц.)** | Cookie `AspNetCore.Cookies` для авторизации в админ-панели без логина/пароля |
| **👁 Показать** | Включает отображение пароля и токена открытым текстом |
| **💾 Сохранить настройки** | Сохраняет все введённые данные в SQLite. При следующем запуске поля заполнятся автоматически |

#### 🔍 Вкладка «Поиск» — сканирование и пробив

**Группа «Режим сканирования»:**

| Элемент | Назначение |
|---|---|
| **🔎 Пробив игрока по нику** | Одиночный режим. Вводишь ник — сканирует Discord + админ-панель, собирает все наказания, связанные аккаунты, IP, HWID, временные метки. Формирует подробный HTML-отчёт |
| **🛡 Проверка обхода банов** | Массовый режим. Сканирует N страниц админ-панели (по 2000 записей каждая), ищет забаненных игроков, которые заходят под другими аккаунтами. Выводит связи HWID/IP/Username |
| **Имя игрока** | Поле ввода ника (активно только в режиме «Пробив по нику») |
| **Кол-во сообщений** | Сколько последних сообщений из канала жалоб Discord загружать (для поиска упоминаний игрока) |
| **Страниц обхода** | Сколько страниц админ-панели сканировать при проверке обхода банов (1 стр. ≈ 2000 записей) |
| **⚡ Авто-бан IP/HWID** | При обнаружении обхода бана — автоматически отправить бан на IP и HWID нарушителя (активно только в режиме «Проверка обхода») |

**Кнопки действий:**

| Кнопка | Назначение |
|---|---|
| **▶ Запуск** | Запускает сканирование в фоновом потоке. Перед запуском показывает информационные диалоги (первый запуск, предупреждение об обходе банов) |
| **■ Остановить** | Прерывает текущее сканирование (отменяет asyncio-задачи и закрывает соединения) |
| **⚙️** | Открывает окно расширенных настроек конфигурации (4 вкладки) |

**Группа «Прогресс»:**

| Элемент | Назначение |
|---|---|
| **Progress bar** | Индикатор выполнения текущей операции |
| **Текст статуса** | Описание текущего этапа + прошедшее время (⏱) |

**Группа «Статус»:**

Окно лога с цветовой маркировкой:
- 🟦 `info` — информационные сообщения (бирюзовый)
- 🟩 `success` — успешные операции (зелёный)
- 🟥 `error` — ошибки (красный)
- 🟨 `warning` — предупреждения (жёлтый/золотой)
- ⬜ `dim` — технические детали (серый)

В лог выводятся все этапы: авторизация в админ-панели, загрузка сообщений из Discord, поиск связей, проверка VPN/хостинга, формирование отчёта.

**После завершения сканирования:**
1. Автоматически проверяет IP на VPN/хостинг через `vpn_detector`
2. Генерирует HTML-отчёт и открывает его в браузере
3. Предлагает сохранить HTML-отчёт в выбранную папку

#### 🔨 Вкладка «Блокировка» — массовая выдача банов

| Элемент | Назначение |
|---|---|
| **🎯 Цели** | Многострочное текстовое поле. Каждая строка — одна цель: HWID, IP-адрес или Username. Тип определяется автоматически |
| **Причина** | Текст причины бана. По умолчанию — «Перманентная блокировка...» |
| **📋 Пресеты** | Открывает окно с шаблонами причин бана: — *Локальные пресеты* (Обход блокировки, ПДК по жалобе, Набег на сервер партнёров, Набегаторский твинк, Перманентная, Набегатор, БВО) — *Пресеты с админ-сайта* (загружаются через админ-панель по кнопке «📥 Загрузить с админки») |
| **🔄 Сброс** | Сбрасывает причину на значение по умолчанию |
| **📍 Забанить последний IP** | Если цель — username, дополнительно банит его последний известный IP |
| **🔑 Забанить последний HWID** | Если цель — username, дополнительно банит его последний известный HWID (включено по умолчанию) |
| **Длительность (мин)** | Длительность бана в минутах. `0` = навсегда |
| **🔨 Выдать блокировку** | Запускает процесс бана: логинится в админ-панель, по каждой цели определяет тип (IP/HWID/UID/Nick), отправляет запрос на создание бана. Результат выводится в окно ниже |

**Группа «Результат»:** окно лога с результатами каждой блокировки (✅ УСПЕХ / ❌ ОШИБКА), итоговой статистикой (успешно/ошибок).

#### ⚙️ Окно расширенных настроек (кнопка ⚙️)

Четыре вкладки с тонкой настройкой:

| Вкладка | Параметры |
|---|---|
| **Discord** | `TARGET_CHANNEL_ID`, `COMPLAINT_CHANNEL_IDS` (список ID каналов жалоб), `MESSAGE_HISTORY_LIMIT` |
| **API** | `BASE_ADMIN_URL`, `ACCOUNT_URL`, таймауты (`OPERATION_TIMEOUT`, `REQUEST_TIMEOUT`, `SEARCH_TIMEOUT`, `BATCH_TIMEOUT`, `TERM_TIMEOUT`), `MAX_CONCURRENT_REQUESTS` |
| **Сканирование** | `SEARCH_MAX_DEPTH`, лимиты поиска (`SEARCH_LIMIT_ROOT`/`LEVEL1`/`LEVEL2`/`DEFAULT`), `BYPASS_SEARCH_MAX_DEPTH`, кэш (`SEARCH_CACHE_MAX_SIZE`, `SEARCH_CACHE_TTL`) |
| **Тайминги** | Пороги совпадения по времени: `CLOSE_TIME_THRESHOLD_MINUTES`, `TIME_THRESHOLD_MINUTES`, `SUSPICIOUS_TIME_THRESHOLD_MINUTES`, `IP_MATCH_TIMEDELTA_MINUTES` |

Изменения сохраняются в SQLite и применяются при следующем запуске.

#### 🎨 Визуальные эффекты

- **Анимированный звёздный фон** — 250 мерцающих звёзд, перерисовывается при изменении размера окна
- **Glass-карточки** — полупрозрачные рамки вокруг блоков интерфейса
- **Цветовая схема** — глубокий тёмно-синий фон (`#070714`), бирюзовые акценты (`#22d3ee`), фиолетовый, золотой, зелёный

### Где искать результаты

- **HTML-отчёт** — открывается автоматически после сканирования, можно сохранить в любую папку
- **JSON-файл** — лежит в папке `reports/` рядом с программой
- **База данных** — файл `deadspace_checker.db` в той же папке, где EXE

### Советы

- При первом запуске скачиваются все сообщения из каналов жалоб — это 10–15 минут. Это нормально.
- Чтобы не ждать каждый раз, скачай готовую базу из Releases
- Если Discord или DeadSpace14 троттлят запросы — уменьши лимиты в настройках (кнопка ⚙️)
- Храни токен Discord и пароль от админки в секрете

---

## Для разработчика

### Сборка EXE

```bash
pip install pyinstaller
pyinstaller DeadSpaceChecker.spec --noconfirm
```

Готовый EXE появится в `dist/DeadSpaceChecker.exe`. Файл `DeadSpaceLogo.png` вшивается внутрь — менять настройки можно через GUI.

### Структура проекта

```
deadspace_checker/              Основной пакет
├── __init__.py
│
├── admin/                      Взаимодействие с админ-панелью SS14
│   ├── __init__.py
│   ├── models.py               ConnectionData, SS14AdminAPI
│   └── panel.py                AdminPanel — login, парсинг таблиц, пагинация, кэш
│
├── config/                     Конфигурация
│   ├── __init__.py              load_file()
│   ├── config_system.py         Config (@dataclass), get_config(), Sections
│   └── default_config.py        Значения по умолчанию
│
├── discord_bot/                Discord self-bot
│   ├── __init__.py
│   └── bot.py                  BanCheckerBot — координатор: сканер + админка + отчёты
│
├── gui/                        Графический интерфейс (tkinter)
│   ├── __init__.py
│   ├── app.py                  BanCheckerGUI — главное окно (1453 строки)
│   ├── config_helper.py        Константы и маппинг конфигов для GUI
│   ├── renderers/
│   │   └── embed.py            Рендеринг Discord Embed
│   ├── tabs/
│   │   └── __init__.py         (вкладки встроены в app.py)
│   └── widgets/
│       ├── ansi_parser.py      Парсинг ANSI-цветов в Tkinter Text
│       ├── log_handler.py      QueueLogHandler → очередь GUI
│       └── queue_stream.py     QueueStream — перехват stdout
│
├── models/                     Модели данных
│   ├── __init__.py
│   ├── complaint.py            ComplaintMessage, ComplaintChannel
│   ├── message.py              DiscordMessage, ScanResult
│   ├── player.py               Player
│   └── verdict.py              VerdictCategory, ConfidenceLevel
│
├── scanner/                    Сканирование и анализ
│   ├── __init__.py
│   ├── analyzer.py             Корреляция игроков по HWID/IP/нике
│   ├── bypass.py               BanBypassMixin — проверка обхода банов
│   ├── message_utils.py        Извлечение данных из сообщений
│   ├── player_merge.py         Слияние данных игрока
│   ├── scanner.py              Главный сканер: загрузка, очередь, circuit breaker
│   └── utils.py                CircuitBreaker, ExponentialBackoff, cached
│
├── services/                   Службы
│   ├── __init__.py
│   ├── admin_service.py        Клиент API админки (наследует PlayerSearchMixin)
│   ├── cache.py                LRUCache
│   ├── cache_service.py        Обёртка для ComplaintChannel над SQLite
│   ├── database_service.py     SQLite-бэкенд (кэш жалоб + настройки GUI)
│   ├── discord_service.py      Работа с Discord, поиск по каналам
│   ├── graph_service.py        Генерация vis.js графа для HTML-отчёта
│   ├── load_optimizer.py       StabilizedLoadOptimizer — адаптивная подстройка
│   ├── search.py               PlayerSearchMixin — поиск игроков
│   ├── vpn_detector.py         Обогащение данных о VPN/хостинге
│   └── reporting/              Генерация отчётов
│       ├── __init__.py
│       ├── service.py          ReportService (оркестратор)
│       ├── report_config.py    ReportConfig + load_config_from_file
│       ├── constants.py        Все константы (BOX_CHARS, DISPLAY_LIMITS, ...)
│       ├── console_printer.py  ConsolePrinterMixin — печать в терминал
│       ├── report_generator.py ReportDataGeneratorMixin — JSON/data отчёты
│       ├── report_format.py    ReportFormatter (базовое форматирование)
│       ├── formatter.py        Formatter (перенаправление)
│       ├── formatter_layout.py FormatterLayoutMixin — сложные layout'ы
│       ├── html_renderer.py    Публичное API HTML-отчётов
│       ├── html_builder.py     Внутренние HTML-компоненты (CSS, секции)
│       ├── utils.py            determine_owner, analyze_hwids, analyze_ips
│       ├── nickname_analysis.py   categorize_associated_nicknames
│       ├── complaint_analysis.py  analyze_complaints
│       └── connection_analysis.py find_connection_paths
│
├── utils/                      Утилиты
│   ├── __init__.py
│   ├── async_utils.py          Утилиты для асинхронной работы
│   ├── discord_patch.py        Патчи для discord.py-self
│   ├── discord_utils.py        Парсинг Discord-ссылок
│   ├── embed_utils.py          Парсинг Discord Embed
│   ├── logging_utils.py        Логирование с ротацией и цветами
│   ├── path_utils.py           PyInstaller-совместимые пути
│   ├── performance_monitor.py  Трекинг производительности
│   └── url_utils.py            Извлечение ссылок и поисковых термов
│
├── tests/                      Тесты
│   ├── conftest.py             Pytest fixtures (SQLite in-memory, DiscordBot mock)
│   ├── test_config_system.py
│   ├── core/test_analyzer.py
│   ├── models/test_complaint.py, test_message.py, test_player.py, test_verdict.py
│   ├── services/test_database_service.py
│   └── services/reporting/test_reporting_utils.py
│   └── utils/test_discord_utils.py, test_url_utils.py
│
├── main.py                     CLI-вход (парсинг аргументов, запуск)
├── build_cache.py              CLI-скрипт для предсоздания БД
```

Корневые файлы:
```
DeadSpaceChecker.spec           Спецификация PyInstaller
requirements.txt                Зависимости
README.md                       Этот файл
```

### Зависимости

Указаны в `requirements.txt`:

| Пакет | Назначение |
|---|---|
| `aiohttp>=3.9` | Асинхронный HTTP-клиент |
| `aiolimiter` | Лимитер скорости запросов |
| `selectolax` | Быстрый HTML-парсер (CSS-селекторы) |
| `discord.py-self>=2.0` | Self-bot библиотека Discord |

### Конфигурация

Основные настройки задаются через GUI (кнопка ⚙️). Для продвинутой настройки — отредактируй `deadspace_checker/config/config_system.py`:

- **Discord**: токен, ID каналов, лимит истории сообщений
- **API**: URL админки, таймауты, конкурентность
- **Сканирование**: глубины поиска, лимиты, кэш
- **Load Optimizer**: адаптивная подстройка под latency
- **Circuit Breaker**: защита от каскадных ошибок
- **Тайминги**: пороги схожести по времени для HWID/IP

Конфиг можно переопределить через GUI — изменения сохраняются в SQLite и применяются при следующем запуске.

Константы отображения (бокс-чарсы, лимиты списков, цветовые схемы) лежат в `deadspace_checker/services/reporting/constants.py`.

### CLI-режимы (без GUI)

```bash
python main.py                                          # Сканирование новых сообщений
python main.py --username Игрок                         # Пробив по нику
python main.py --check-ban-bypass --ban-bypass-pages 10 # Проверка обхода банов
```

Аргументы `--config`, `--log-level` тоже поддерживаются. Discord-бот запускается через `python -m deadspace_checker.discord_bot.bot`.

### Создание БД без GUI

```bash
python build_cache.py --token ВАШ_DISCORD_ТОКЕН
```

После завершения появится `deadspace_checker.db`. Его можно распространять в релизах, чтобы пользователям не ждать 10–15 минут при первом запуске.

### Тестирование

```bash
python -m pytest tests/ -v
```

162 теста покрывают модели, утилиты, DatabaseService, reporting и analysis-функции.

---

## Лицензия

MIT. Использование ограничено легитимными сценариями модерации и безопасности.
