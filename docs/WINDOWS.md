# Windows: браузер и mpv.net

Откройте адрес Lampac с сервера. Для установки внешнего плеера откройте **PowerShell на Windows**, в каталоге клона HomeCinema:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\windows\install.ps1 -ServerUrl 'http://SERVER_IP:9118'
```

Замените SERVER_IP адресом сервера. Если mpv.net уже установлен и не находится автоматически:

```powershell
.\windows\install.ps1 -ServerUrl 'http://SERVER_IP:9118' -MpvPath 'C:\Path\To\mpvnet.exe'
```

Установщик сохраняет конфигурацию в `%LOCALAPPDATA%\HomeCinemaMpvBridge`, конфиги плеера — в `%APPDATA%\mpv.net`, создаёт задачу автозапуска. Локальный bridge использует порт 19777 и разрешает origin заданного сервера. Старые конфиги плеера резервируются.

Это ранее подготовленный Windows-комплект, включённый без новой проверки на реальном ПК. Восстановление bridge после сна остаётся открытой задачей. Если Lampac поменял адрес, повторно запустите установщик с новым ServerUrl. Linux fish по SSH не выполняет команды PowerShell и не видит Windows Downloads.

## Сервер в Ubuntu / WSL на этом же ПК

Docker внутри Ubuntu и Docker Desktop — разные установки. Для сервера из Ubuntu
нужно запускать именно эту WSL-дистрибуцию. Даже включённый `docker.service`
не удерживает WSL после выхода последнего Windows-клиента:
[ограничение systemd в WSL](https://learn.microsoft.com/en-us/windows/wsl/systemd/).
Признак: `wsl --list --verbose` показывает Ubuntu как Stopped; краткий вызов
`wsl -d Ubuntu ...` запускает контейнеры, но вскоре они снова недоступны.

В PowerShell из каталога HomeCinema выполните:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\windows\install-wsl-server.ps1 -Distribution Ubuntu
```

Установщик создаёт задачу `HomeCinemaWsl-Ubuntu` для текущего пользователя
и сразу запускает её. При каждом входе этого пользователя в Windows она
запускает Ubuntu в фоне без окна и держит Windows-клиент WSL подключённым.
Скрипт хранится в `%LOCALAPPDATA%\HomeCinemaWsl-Ubuntu`; checkout можно перемещать.
После выхода WSL скрипт пробует запустить её снова через 10 секунд.
Задача не ограничена тремя днями и может работать от батареи.
Это запуск после входа пользователя, а не до входа в Windows.

В Ubuntu должны быть включены systemd и Docker, а у контейнеров — политика
перезапуска (`unless-stopped` в штатном Compose). Скрипт не переустанавливает
Docker и не меняет контейнеры, конфигурацию, историю или настройки сети.
На этом ПК открывайте [Лампу](http://localhost:9118/).
Доступ с ТВ по LAN — отдельная настройка сети WSL, этим установщиком не выполняется.

Проверка в PowerShell:

```powershell
Get-ScheduledTask -TaskName HomeCinemaWsl-Ubuntu
curl.exe --noproxy "*" --fail http://localhost:9118/ -o NUL
wsl -d Ubuntu -- bash -lc 'cd ~/HomeCinema && bash server/healthcheck.sh'
```

Перед намеренным выключением WSL сначала остановите задачу, иначе она запустит
Ubuntu снова. Для возврата фонового запуска вызовите `Start-ScheduledTask`:

```powershell
Stop-ScheduledTask -TaskName HomeCinemaWsl-Ubuntu
wsl --terminate Ubuntu
Start-ScheduledTask -TaskName HomeCinemaWsl-Ubuntu
```

Удаление автозапуска без удаления WSL и данных:

```powershell
.\windows\install-wsl-server.ps1 -Distribution Ubuntu -Remove
```

На действующем Windows/WSL проверены установка задачи, её фоновая работа,
доступ к HTML/JS/CSS Lampac и штатная проверка четырёх серверных сервисов.
Полный перезапуск Windows и следующий вход пользователя отдельно не проверялись.
Общий `bash scripts/check.sh` запускался в чистой копии исходников: семь тестов
первоначальной установки прошли, затем прогон остановился из-за отсутствующего
Node.js в Ubuntu. Это ограничение окружения проверки, а не результат полного прогона.
