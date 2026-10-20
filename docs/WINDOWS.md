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
