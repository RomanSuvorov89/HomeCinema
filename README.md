# HomeCinema

Домашний кинотеатр: Lampa/Lampac, TorrServer, локальный каталог и рекомендации по Кинопоиску, сохранённые постеры, синхронизация просмотра и Windows mpv.net bridge.

Репозиторий хранит исходники и команды для восстановления системы после переезда. **Версия 0.3.0 — preview:** отдельные исправления проверены на действующей установке; полная установка этого объединённого комплекта на чистую машину ещё требует проверки. Рабочую систему сейчас переустанавливать не нужно.

## Новая установка на Linux

Сначала установите Git и Docker с Compose. Для CachyOS/Arch:

```sh
sudo pacman -S --needed git docker docker-compose curl jq python
sudo systemctl enable --now docker
```

Клонируйте репозиторий, подготовьте настройки:

```sh
git clone https://github.com/RomanSuvorov89/HomeCinema.git
cd HomeCinema
cp config/stack.env.example config/stack.env
cp config/profiles.example.json config/profiles.json
cp config/rating-scale.example.json config/rating-scale.json
```

В `config/stack.env` укажите LAN-адрес нового сервера во всех четырёх `PUBLIC_*_URL`, пароль Lampac и активный профиль. В `config/profiles.json` заполните ID своего публичного профиля Кинопоиска и собственный `lampac_sync_id`. Адреса должны открываться с телевизоров. Желательно закрепить IP сервера в DHCP роутера.

Запуск, в том числе из fish:

```sh
bash server/install.sh
bash server/healthcheck.sh
```

Если у пользователя нет доступа к Docker, установщик использует `sudo docker`. Для диагностических команд и резервного копирования в таком случае также используйте `sudo`. Установщик умеет поставить зависимости через `bash server/install.sh --install-deps`.

| Сервис | Порт по умолчанию | Данные |
|---|---:|---|
| Lampac / Lampa | 9118 | `server/data/lampac` |
| TorrServer | 8090 | `server/data/torrserver` |
| Каталог и рекомендации | 9120 | `server/data/recommender` |
| Кэш постеров Кинопоиска | 9121 | `server/data/poster-cache` |

На ТВ и ПК откройте `PUBLIC_LAMPAC_URL`. Центральный клиент подключает каталог, Family Sync, постеры, предзагрузку и bridge. Для Windows плеера: [инструкция](docs/WINDOWS.md). Для Android TV: [инструкция](android/README.md).

## Перенос существующей установки

**Код в Git не заменяет резервную копию истории и баз.** Перед переездом выполните [инструкцию экспорта и восстановления](docs/MIGRATION.md). Она охватывает нынешние отдельные контейнеры и новую общую установку.

Для установки из этого репозитория:

```sh
bash server/backup.sh /path/to/external-disk/homecinema
```

Скрипт останавливает работающие сервисы на время согласованного копирования SQLite и затем запускает их обратно. Архив содержит личную историю и настройки; храните его отдельно от публичного Git.

## Обновление и диагностика

Перед обновлением сделайте резервную копию. Затем:

```sh
git pull --ff-only
bash server/update.sh
bash server/healthcheck.sh
docker compose --env-file server/.runtime.env -f server/docker-compose.yml ps
docker compose --env-file server/.runtime.env -f server/docker-compose.yml logs --tail 100
```

Обновление пересобирает плагины из шаблонов, сохраняет прежний `lampainit.js` и не удаляет базы. После него полностью перезапустите Lampa на ТВ; в браузере нажмите Ctrl+F5. Образы Lampac и TorrServer используют `latest`; перед переездом сохраняйте фактические образы по инструкции, поскольку их будущие версии могут отличаться.

- [Что включено и что проверено](docs/FEATURES.md)
- [Архитектура](docs/ARCHITECTURE.md)
- [Ограничения](docs/KNOWN_ISSUES.md)
- [Оформление Apple TV и откат](docs/APPEARANCE.md)
- [TODO](TODO.md)
- [Контекст для дальнейших доработок](docs/CONTEXT.md)

Сторонние сервисы и образы устанавливаются из их проектов. Это репозиторий интеграции и собственных дополнений; доступность внешних источников зависит от сети.

## Проверки исходников

Нужны Python 3, Node.js и bash. Команда `bash scripts/check.sh` проверяет шаблоны и синтаксис, серверные компоненты и клиентские сценарии без обращения к реальному серверу. Docker-сборка, Windows PowerShell и реальные телевизоры проверяются отдельно.
