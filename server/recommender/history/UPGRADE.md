# Обновление до 0.7.4

Исправлены циклический объект в ключе кеша и «Ещё» персонального ряда.
Карточки без прогноза не попадают в «Сейчас смотрят — для тебя».
Подробности: UPDATE_074.md.

```fish
cd /home/USER/kinopoisk-sync
and tar --exclude=docker-compose.yml -xzf /home/USER/kinopoisk-sync.tar.gz -C /home/USER/kinopoisk-sync
and python install.py
and docker restart lampac
and docker compose up -d --build --force-recreate
```

После первой новой записи `home cache` обновить браузер Ctrl+F5,
на ТВ остановить приложение и открыть заново. APK не менять.

---

# Обновление до 0.7.3

Списки исправляются из сохранённого кеша даже при недоступности Lampac.
«Огонь» сохраняет актуальные оценённые фильмы. Подробности: UPDATE_073.md.

```fish
cd /home/USER/kinopoisk-sync
and tar --exclude=docker-compose.yml -xzf /home/USER/kinopoisk-sync.tar.gz -C /home/USER/kinopoisk-sync
and python install.py
and docker restart lampac
and docker compose up -d --build --force-recreate
```

После первой новой записи `home cache` обновить браузер Ctrl+F5,
на ТВ остановить приложение и открыть заново. APK не менять.
Проверка доступности Lampac из контейнера:

```fish
docker exec kinopoisk-sync curl -sS --max-time 8 -o /dev/null -w 'Lampac HTTP %{http_code}\n' http://127.0.0.1:9118/lampainit.js
```

---

# Обновление до 0.7.2

Исправлены преждевременное появление будущего сезона и персонализация «Огня» /
«Сейчас смотрят». Подробности и ограничения: UPDATE_072.md.

```fish
cd /home/USER/kinopoisk-sync
and tar --exclude=docker-compose.yml -xzf /home/USER/kinopoisk-sync.tar.gz -C /home/USER/kinopoisk-sync
and docker compose up -d --build --force-recreate
and python install.py
and docker restart lampac
```

На ПК Ctrl+F5. На ТВ остановить приложение и открыть заново; APK не менять.
Дождаться первой новой записи `home cache`, затем повторно открыть главную.

```fish
docker logs --since 10m kinopoisk-sync 2>&1 | rg 'episode schedule|home cache'
curl -fsS http://127.0.0.1:9120/home.json | jq '.rows[] | select(.kind == "continue" or .kind == "fire" or .kind == "now") | {kind, cards: [.results[:8][] | {title, name, kinopoisk_id, details: .roman_review}]}'
```

---

# Обновление до 0.7.1

Отдельная загрузка расписаний /episodes/ и кругляшка в конце подгружаемого списка.
Формула прогноза 0.7.0 не меняется. Подробности: UPDATE_071.md.

Скопировать новый kinopoisk-sync.tar.gz в /home/USER/kinopoisk-sync.tar.gz.

```fish
cd /home/USER/kinopoisk-sync
and tar --exclude=docker-compose.yml -xzf /home/USER/kinopoisk-sync.tar.gz -C /home/USER/kinopoisk-sync
and python prioritize_episodes.py 5024113
and docker compose up -d --build --force-recreate
and python install.py
and docker restart lampac
```

На ПК Ctrl+F5. На ТВ остановить приложение и открыть заново; APK не менять.
Приоритет проверяет расписание Тёмной материи первой, без подмены условия «есть личная оценка».
В фоне обновляются только расписания; вся база метаданных повторно не выгружается.
После появления серверного ряда повторно открыть главную, чтобы взять свежую копию.

```fish
docker logs --since 5m kinopoisk-sync 2>&1 | rg 'episode schedule|home cache'
curl -fsS http://127.0.0.1:9120/home.json | jq '.rows[] | select(.kind == "continue") | .results'
```

Если ряд всё ещё пустой, диагностический запрос (SQLite только читает):

```fish
sqlite3 -readonly -box /home/USER/kinopoisk-sync/data/recommender.sqlite3 "SELECT m.kp_id,m.title,m.media_type,ur.rating,e.checked_at,e.error,st.airing_state,st.last_air_date,st.next_air_date FROM media m LEFT JOIN user_ratings ur ON ur.kp_id=m.kp_id LEFT JOIN episode_schedules e ON e.kp_id=m.kp_id LEFT JOIN series_tracking st ON st.kp_id=m.kp_id AND st.profile_id=ur.profile_id WHERE m.kp_id=5024113;"
```

---

# Обновление до 0.7.0

Оценённые сериалы в период выхода добавляются в «Продолжить просмотр».
Прогноз калибруется по шкале владельца профиля. «Ещё» сохраняет полный список
и карточки; повторное открытие использует локальный снимок и фоновую проверку ревизии.
Подробности формул и ограничений: UPDATE_070.md.

```fish
cd /home/USER/kinopoisk-sync
and tar --exclude=docker-compose.yml -xzf /home/USER/kinopoisk-sync.tar.gz -C /home/USER/kinopoisk-sync
and docker compose up -d --build --force-recreate
and python install.py
and docker restart lampac
```

На ПК Ctrl+F5. На ТВ остановить приложение через настройки Android и открыть заново.
APK менять не нужно. Windows Bridge не обновляется, выбор плеера сохраняется.
Первый фоновый прогрев новых списков требует времени; старые готовые карточки доступны сразу.
При первом получении нового снимка сериалы сохраняются для следующего открытия главной.

```fish
curl -fsS http://127.0.0.1:9120/home.json | jq '.rows[] | select(.kind == "continue") | {title, series: [.results[] | {title, name, details: .roman_review}]}'
curl -fsS http://127.0.0.1:9120/prediction-calibration.json | jq
curl -fsS http://127.0.0.1:9120/review-cached.json | jq '{revision, count: (.items|length), ready_cards: ([.items[]|select(.card)]|length), warming}'
```

---

# Обновление до 0.6.0-home-cache

Фоновый серверный кэш готовых разделов; открытие главной больше не запускает
поиск карточек для её персональных рядов. Схема/TTL/поведение без KP: HOME_CACHE.md.
APK и Windows Bridge не меняются, данные и Compose сохраняются.

```fish
cd /home/USER/kinopoisk-sync
and tar --exclude=docker-compose.yml -xzf /home/USER/kinopoisk-sync.tar.gz -C /home/USER/kinopoisk-sync
and docker compose up -d --build --force-recreate
and python install.py
and docker restart lampac
```

Первый серверный прогрев выполняется в фоне один раз; он может занять время.
На ТВ сначала доступны Continue/Fire и прежняя клиентская копия; новые группы
сохраняются для следующего открытия. Проверить готовность кэша:

```fish
curl -fsS http://127.0.0.1:9120/home.json | jq '{groups: [.rows[] | {kind, count: (.results|length)}], status}'
```

Когда снимки готовы, остановить Lampac через настройки приложений и открыть;
на ПК Ctrl+F5. Кэш приложения/данные не очищать. Дальнейшее обновление происходит
на сервере по таймеру, при входе читается готовый снимок по LAN.

---

# Обновление до 0.5.5-cub-search

Исправлена подтверждённая логом ошибка `catalog.get is not a function`:
CUB не экспортирует get; поиск теперь использует публичный list(params, success, error).
Это исправляет получение карточек при пустом кэше (новый ТВ), а не скрывает уведомления.
Существующий кэш ПК сохраняется. ViMu, настройки дорожек и Windows Bridge не меняются.

Заменить `/home/USER/kinopoisk-sync.tar.gz` новым архивом, выполнить в Linux:

```fish
cd /home/USER/kinopoisk-sync
and tar --exclude=docker-compose.yml -xzf /home/USER/kinopoisk-sync.tar.gz -C /home/USER/kinopoisk-sync
and docker compose up -d --build --force-recreate
and python install.py
and docker restart lampac
```

На ТВ остановить Lampac через настройки приложений и открыть заново; на ПК Ctrl+F5.
Не очищать данные приложения. APK прежний.

Проверка: node test_catalog_resolver.cjs использует реальную реализацию публичного
CUB list и проверяет холодный кэш, 12 параллельно разрешаемых карточек, кодирование
русского запроса с &, сохранность кэша и завершение очереди при ошибке.
Обнаруженный в логе отдельный сбой CUB shots этим обновлением не исправляется.

---

# Обновление до 0.5.4-tv-bootstrap

Скопировать новый `kinopoisk-sync.tar.gz` в `/home/USER/kinopoisk-sync.tar.gz`, затем в Linux (fish):

```fish
cd /home/USER/kinopoisk-sync
and tar --exclude=docker-compose.yml -xzf /home/USER/kinopoisk-sync.tar.gz -C /home/USER/kinopoisk-sync
and docker compose up -d --build --force-recreate
and python install.py
and docker restart lampac
```

На ТВ: Настройки Android → Приложения → Lampac → Остановить, затем открыть.
APK переустанавливать и данные приложения очищать не требуется.
При первом запуске воспроизведения выбрать ViMu или другой установленный плеер.
Миграция снимает прежний выбор плеера однократно. Последующий выбор сохраняется.
На ПК достаточно перезагрузить страницу. Windows MPV Bridge не изменяется.

Если интерфейс всё ещё неправильный, после запуска на ТВ выполнить:

```fish
curl -fsS http://127.0.0.1:9120/client-diagnostics.json | jq
```

Это автоматический журнал клиента: версия, браузерный движок, стадия, ошибка/адрес
незагрузившегося скрипта и флаг перехвата CUB. До 100 записей в памяти сервера;
при перезапуске контейнера сбрасывается. События также идут в docker logs.

Изменения и ограничения: TV_FIX.md. На физическом ТВ сборка ещё не проверена.

---

# Обновление до 0.5.3-tv-defaults

Устанавливается на сервер, APK менять не нужно. Новое обязательное действие:
`python install.py` добавляет настройки до открытия первой страницы на клиенте.
Сохраняет резервную копию lampainit, прочие плагины и Windows Bridge.

```fish
cd /home/USER/kinopoisk-sync
and tar --exclude=docker-compose.yml -xzf /home/USER/kinopoisk-sync.tar.gz -C /home/USER/kinopoisk-sync
and docker compose up -d --build --force-recreate
and python install.py
and docker restart lampac
```

После завершения на ТВ принудительно остановить Lampac и открыть снова.
Данные приложения очищать не нужно. На ПК — Ctrl+F5.
Подробности, ограничения проверки и причины ошибок: TV_FIX.md.

---

# Обновление рекомендателя до 0.5.2-home-fast

Для обновления с 0.4.1 / 0.5.0 / 0.5.1 пересоберите только контейнер kinopoisk-sync и обновите
Lampa через Ctrl+F5. Windows Bridge, Lampac и установщик дорожек повторно запускать
не требуется. Детали новой главной, формулы и ограничений: HOME.md.

```fish
cd /home/USER/kinopoisk-sync
and tar -xzf /home/USER/kinopoisk-sync.tar.gz -C /home/USER/kinopoisk-sync
and docker compose up -d --build --force-recreate
```

## Предыдущие обновления

Версия включает запоминание дорожек сериалов. Для текущего обновления используйте
полные команды из TRACK_MEMORY.md: обновляются сервер, клиентский блок Bridge и
скрипт Windows с сохранением конфигурации и задачи планировщика.

На главной CUB строка «Рекомендуем посмотреть» заменяется на «Рекомендация AI».
«Ещё» открывает список с фильтрами сверху. Добавлен предварительный прогноз оценки.
Старые отдельные пункты рекомендаций и фильтров убраны. После обновления перезагрузите Lampa
через Ctrl+F5. Windows MPV Bridge и конфигурация Lampac не изменяются.
Описание API и таблицы: REVIEW.md.

Версия добавляет кандидатный каталог из четырёх списков Кинопоиска и формирует
проверочные рекомендации, доступные на главной CUB.

При старте контейнер создаёт консистентный снимок SQLite в `data/backups/` и хранит
последние пять снимков.

## Установка

```fish
cd /home/USER/kinopoisk-sync

tar -xzf /home/USER/kinopoisk-sync.tar.gz \
    -C /home/USER/kinopoisk-sync

docker compose up -d --build --force-recreate

docker logs --tail 100 -f kinopoisk-sync
```

Ожидаемые стадии в логе:

```text
database snapshot: /data/backups/...
candidate catalog: ...
kinopoisk metadata: ...
```

## Проверка

```fish
curl -fsS http://127.0.0.1:9120/recommendations.json \
    | jq '.catalog, .scored_count'

curl -fsS http://127.0.0.1:9120/recommendations.json \
    | jq '.groups[0].items[:10] | map({title, release_year, kp_rating, predicted_rating, final_score, reasons})'
```

Пока новые кандидаты обрабатываются, `catalog.remaining` будет уменьшаться, а список
пересчитываться после каждой партии.
