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

Программа запускается как обычное окно Windows. Все настройки вводятся в поля и сохраняются кнопкой **Сохранить настройки**.

**Поля для заполнения:**
- Имя и пароль администратора (от DeadSpace14)
- Токен Discord
- Количество сообщений для сканирования
- Количество страниц для проверки обхода банов

**Три режима работы:**

| Режим | Что делает |
|---|---|
| **Пробив игрока по нику** | Вводишь ник — получаешь наказания, связанные аккаунты, IP, HWID, жалобы |
| **Сканирование новых сообщений** | Мониторит канал «Arrived new player», собирает всех новых игроков |
| **Проверка обхода банов** | Массовая проверка: ищет, не заходит ли забаненный игрок под другими аккаунтами |

После завершения любого режима можно сформировать **HTML-отчёт** — он откроется в браузере.

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
gui/                            Графический интерфейс (tkinter)
├── app.py                      Основное окно
├── config_helper.py            Помощник конфигурации
├── renderers/embed.py          Рендеринг Discord Embed
├── tabs/                       Вкладки интерфейса
└── widgets/                    Виджеты (ANSI-парсер, логи, очередь)

scanner/                        Сканирование и анализ
├── scanner.py                  Главный сканер: загрузка, очередь, circuit breaker
├── analyzer.py                 Корреляция игроков по HWID/IP/нике
├── bypass.py                   BanBypassMixin — проверка обхода банов
├── message_utils.py            Извлечение данных из сообщений
├── player_merge.py             Слияние данных игрока
└── utils.py                    CircuitBreaker, ExponentialBackoff, cached

services/
├── admin_service.py            Клиент API админки (наследует PlayerSearchMixin)
├── cache.py                    LRUCache
├── cache_service.py            Обёртка для ComplaintChannel над SQLite
├── database_service.py         SQLite-бэкенд (кэш жалоб + админ-кэш + настройки)
├── discord_service.py          Работа с Discord, поиск по каналам
├── graph_service.py            Генерация vis.js графа для HTML-отчёта
├── load_optimizer.py           StabilizedLoadOptimizer — адаптивная подстройка
├── search.py                   PlayerSearchMixin — поиск игроков
├── vpn_detector.py             Обогащение данных о VPN/хостинге
└── reporting/                  Генерация отчётов
    ├── service.py              ReportService (оркестратор)
    ├── config.py               ReportConfig + load_config_from_file
    ├── constants.py            Все константы (BOX_CHARS, DISPLAY_LIMITS, ...)
    ├── console_printer.py      ConsolePrinterMixin — печать в терминал
    ├── report_generator.py     ReportDataGeneratorMixin — JSON/data отчёты
    ├── formatter.py            ReportFormatter (базовое форматирование)
    ├── formatter_layout.py     FormatterLayoutMixin — сложные layout'ы
    ├── html_renderer.py        Публичное API HTML-отчётов
    ├── html_builder.py         Внутренние HTML-компоненты (CSS, секции)
    ├── utils.py                determine_owner, analyze_hwids, analyze_ips
    ├── nickname_analysis.py    categorize_associated_nicknames
    ├── complaint_analysis.py   analyze_complaints
    └── connection_analysis.py  find_connection_paths

models/
├── player.py                   Модель игрока
├── message.py                  DiscordMessage, ScanResult
├── complaint.py                ComplaintMessage, ComplaintChannel
└── verdict.py                  VerdictCategory, ConfidenceLevel

utils/
├── path_utils.py               PyInstaller-совместимые пути
├── logging_utils.py            Логирование с ротацией и цветами
├── async_utils.py              Утилиты для асинхронной работы
├── discord_utils.py            Парсинг Discord-ссылок
├── url_utils.py                Извлечение ссылок и поисковых термов
├── embed_utils.py              Парсинг Discord Embed
└── performance_monitor.py      Трекинг производительности

main.py                         CLI-вход (парсинг аргументов, запуск)
build_cache.py                  CLI-скрипт для предсоздания БД
DeadSpaceChecker.spec           Спецификация PyInstaller
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
