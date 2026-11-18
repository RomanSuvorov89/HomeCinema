param([switch]$Check)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

try {
    $Config = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'server-panel.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($Config.Distribution -notmatch '^[A-Za-z0-9_.-]+$') { throw 'Неверное имя дистрибутива WSL.' }
    $TaskName = 'WslServer-' + $Config.Distribution
    $WslPath = Join-Path $env:SystemRoot 'System32\wsl.exe'
    $Controller = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'wsl-server-control.sh') -Raw -Encoding UTF8
    $script:Work = $null
    $script:NextStatus = [DateTime]::MaxValue
    $script:CloseAfterWork = $false
    $ActionNames = @{status='Состояние Linux';health='Проверка служб Linux';logs='Журнал контейнера';resources='Ресурсы контейнеров';disk='Использование диска Docker';'linux-resources'='Ресурсы Linux';'restart-container'='Перезапуск контейнера';'start-container'='Запуск контейнера';'stop-container'='Остановка контейнера';'wsl-stop'='Остановка Ubuntu';'wsl-restart'='Перезапуск Ubuntu';'list-wsl'='Дистрибутивы WSL'}

    function Quote-Argument([string]$Value) {
        # Windows CommandLineToArgvW quoting, including paths with spaces.
        # WSL's leading switches must remain unquoted in its raw command line.
        if ($Value -ne '' -and $Value -notmatch '[\s"]') { return $Value }
        return '"' + ([regex]::Replace([regex]::Replace($Value, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1')) + '"'
    }
    function Get-TaskSummary {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($null -eq $task) { return 'Фоновая задача не установлена. Повторите установку панели.' }
        $info = $task | Get-ScheduledTaskInfo
        $startup = if ($task.Settings.Enabled) { 'включён' } else { 'выключен' }
        return "Фоновая задача: $($task.State)   Автозапуск: $startup`r`nПоследний запуск: $($info.LastRunTime)"
    }
    function Ensure-Background {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
        if (-not $task.Settings.Enabled) { Enable-ScheduledTask -TaskName $TaskName | Out-Null }
        if ($task.State -ne 'Running') { Start-ScheduledTask -TaskName $TaskName }
    }
    function Show-Error([string]$Message) {
        [System.Windows.Forms.MessageBox]::Show($form, $Message, 'Linux / WSL', 'OK', 'Error') | Out-Null
    }
    function Test-LinuxRunning {
        $info = New-Object System.Diagnostics.ProcessStartInfo
        $info.FileName = $WslPath
        $info.Arguments = '--list --running --quiet'
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $info.RedirectStandardOutput = $true
        $info.StandardOutputEncoding = [System.Text.Encoding]::Unicode
        $process = [System.Diagnostics.Process]::Start($info)
        try {
            $names = $process.StandardOutput.ReadToEnd()
            $process.WaitForExit()
            return [string]$Config.Distribution -in @(($names -replace "`0",'') -split '\r?\n' | ForEach-Object { $_.Trim() })
        } finally { $process.Dispose() }
    }
    function Start-Operation([string]$Action, [string]$Target = '', [bool]$AllowWake = $false) {
        if ($null -ne $script:Work) { return }
        try {
            $taskText.Text = Get-TaskSummary
            if (-not $AllowWake -and $Action -notin @('wsl-stop','wsl-restart','list-wsl') -and -not (Test-LinuxRunning)) {
                $output.Text = "$($Config.Distribution) остановлена. Нажмите «Запустить Ubuntu» или «Терминал Linux»."
                $status.Text = 'Linux остановлен — проверка состояния не включает его автоматически.'
                return
            }
            $output.Text = "$($ActionNames[$Action])…`r`n"
            $status.Text = 'Работаем… Окно можно закрыть, сервер продолжит работать.'
            $info = New-Object System.Diagnostics.ProcessStartInfo
            $info.FileName = $WslPath
            $direct = $Action -in @('wsl-stop','wsl-restart','list-wsl')
            $parts = if ($Action -eq 'list-wsl') { @('--list','--verbose') }
                     elseif ($direct) { @('--terminate',[string]$Config.Distribution) }
                     else { @('--distribution', [string]$Config.Distribution, '--exec', 'bash', '-s', '--', $Action, $Target) }
            $info.Arguments = ($parts | ForEach-Object { Quote-Argument $_ }) -join ' '
            $info.UseShellExecute = $false
            $info.CreateNoWindow = $true
            $info.RedirectStandardInput = $true
            $info.RedirectStandardOutput = $true
            $info.RedirectStandardError = $true
            $info.StandardOutputEncoding = [System.Text.Encoding]::UTF8
            $info.StandardErrorEncoding = [System.Text.Encoding]::UTF8
            if ($Action -eq 'list-wsl') { $info.StandardOutputEncoding = [System.Text.Encoding]::Unicode }
            $process = [System.Diagnostics.Process]::Start($info)
            $outTask = $process.StandardOutput.ReadToEndAsync()
            $errTask = $process.StandardError.ReadToEndAsync()
            if (-not $direct) { $process.StandardInput.Write($Controller.Replace("`r`n", "`n")) }
            $process.StandardInput.Close()
            $script:Work = @{ Process=$process; Out=$outTask; Err=$errTask; Action=$Action; Started=Get-Date }
        } catch { $status.Text = 'Не удалось выполнить действие'; Show-Error $_.Exception.Message }
    }
    function Start-Linux {
        try { Ensure-Background; Start-Operation 'status' '' $true }
        catch { Show-Error $_.Exception.Message }
    }
    function Confirm-Operation([string]$Action, [string]$Message, [string]$Target = '') {
        if ($null -ne $script:Work) { return }
        if ([System.Windows.Forms.MessageBox]::Show($form, $Message, 'Linux / WSL', 'YesNo', 'Question') -eq 'Yes') {
            Start-Operation $Action $Target
        }
    }
    function Stop-Linux([bool]$Restart) {
        if ($null -ne $script:Work) { return }
        $verb = if ($Restart) { 'Перезапустить' } else { 'Остановить' }
        $message = "$verb $($Config.Distribution) целиком? Все приложения, службы и Docker-контейнеры внутри этой Ubuntu остановятся. Другие дистрибутивы WSL не затрагиваются."
        if ([System.Windows.Forms.MessageBox]::Show($form,$message,'Linux / WSL','YesNo','Warning') -ne 'Yes') { return }
        try {
            Disable-ScheduledTask -TaskName $TaskName | Out-Null
            Stop-ScheduledTask -TaskName $TaskName
            Start-Operation $(if ($Restart) { 'wsl-restart' } else { 'wsl-stop' })
        } catch { Show-Error $_.Exception.Message }
    }
    function Open-Terminal {
        try { Ensure-Background; Start-Process -FilePath $WslPath -ArgumentList @('--distribution',[string]$Config.Distribution) | Out-Null }
        catch { Show-Error $_.Exception.Message }
    }
    $form = New-Object System.Windows.Forms.Form
    $form.Text = ($Config.Distribution + ' — управление Linux / WSL')
    $form.Size = New-Object System.Drawing.Size(1080, 760)
    $form.MinimumSize = New-Object System.Drawing.Size(800, 560)
    $form.StartPosition = 'CenterScreen'
    $form.Font = New-Object System.Drawing.Font('Segoe UI', 10)
    $form.BackColor = [System.Drawing.Color]::FromArgb(245,247,250)

    $menu = New-Object System.Windows.Forms.MenuStrip
    $serverMenu = $menu.Items.Add('Linux / WSL')
    $startItem = $serverMenu.DropDownItems.Add('Запустить Ubuntu')
    $startItem.Add_Click({ Start-Linux })
    $terminalItem = $serverMenu.DropDownItems.Add('Открыть терминал Linux')
    $terminalItem.Add_Click({ Open-Terminal })
    $listItem = $serverMenu.DropDownItems.Add('Все дистрибутивы WSL')
    $listItem.Add_Click({ Start-Operation 'list-wsl' })
    $stopItem = $serverMenu.DropDownItems.Add('Остановить Ubuntu целиком')
    $stopItem.Add_Click({ Stop-Linux $false })
    $restartItem = $serverMenu.DropDownItems.Add('Перезапустить Ubuntu целиком')
    $restartItem.Add_Click({ Stop-Linux $true })
    $viewMenu = $menu.Items.Add('Просмотр')
    $stateItem = $viewMenu.DropDownItems.Add('Состояние Linux и все контейнеры')
    $stateItem.Add_Click({ Start-Operation 'status' })
    $healthItem = $viewMenu.DropDownItems.Add('Службы Linux')
    $healthItem.Add_Click({ Start-Operation 'health' })
    $linuxItem = $viewMenu.DropDownItems.Add('Ресурсы Linux и процессы')
    $linuxItem.Add_Click({ Start-Operation 'linux-resources' })
    $resourceItem = $viewMenu.DropDownItems.Add('Ресурсы контейнеров')
    $resourceItem.Add_Click({ Start-Operation 'resources' })
    $diskItem = $viewMenu.DropDownItems.Add('Использование диска Docker')
    $diskItem.Add_Click({ Start-Operation 'disk' })
    $workerItem = $viewMenu.DropDownItems.Add('Журнал фонового запуска')
    $workerItem.Add_Click({
        if ($null -eq $script:Work) {
            $log = Join-Path $PSScriptRoot 'background.log'
            $output.Text = if (Test-Path -LiteralPath $log) { (Get-Content -LiteralPath $log -Tail 100 -Encoding UTF8) -join "`r`n" } else { 'Журнал пока пуст.' }
            $status.Text = 'Журнал фонового запуска WSL'
        }
    })
    $startupMenu = $menu.Items.Add('Автозапуск')
    $enableItem = $startupMenu.DropDownItems.Add('Включить автозапуск сервера')
    $enableItem.Add_Click({ try { Ensure-Background; $taskText.Text=Get-TaskSummary } catch { Show-Error $_.Exception.Message } })
    $disableItem = $startupMenu.DropDownItems.Add('Выключить автозапуск (сервер продолжит работать)')
    $disableItem.Add_Click({ try { Disable-ScheduledTask -TaskName $TaskName | Out-Null; $taskText.Text=Get-TaskSummary } catch { Show-Error $_.Exception.Message } })
    $helpMenu = $menu.Items.Add('Справка')
    $aboutItem = $helpMenu.DropDownItems.Add('Как работает панель')
    $aboutItem.Add_Click({ [System.Windows.Forms.MessageBox]::Show($form, "Это панель всего Linux-дистрибутива $($Config.Distribution).`r`nЗакрытие панели НЕ выключает Ubuntu.`r`nОстановка Ubuntu выключает все службы и контейнеры в ней.`r`nСписок Docker показывает все проекты.`r`nОстановленная через меню Ubuntu не запускается повторно до команды Запустить.`r`n`r`nФоновая задача: $TaskName", 'Linux / WSL') | Out-Null })
    $form.MainMenuStrip = $menu

    $layout = New-Object System.Windows.Forms.TableLayoutPanel
    $layout.Dock = 'Fill'
    $layout.Padding = New-Object System.Windows.Forms.Padding(16)
    $layout.ColumnCount = 1
    $layout.RowCount = 5
    foreach ($height in @(44,60,50)) { [void]$layout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle('Absolute',$height))) }
    [void]$layout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle('Percent',100)))
    [void]$layout.RowStyles.Add((New-Object System.Windows.Forms.RowStyle('Absolute',42)))
    $title = New-Object System.Windows.Forms.Label
    $title.Text = $Config.Distribution + ' / WSL'
    $title.Font = New-Object System.Drawing.Font('Segoe UI', 21, [System.Drawing.FontStyle]::Bold)
    $title.Dock = 'Fill'
    $taskText = New-Object System.Windows.Forms.Label
    $taskText.Dock = 'Fill'
    $taskText.Text = 'Проверяем фоновый запуск…'
    $buttons = New-Object System.Windows.Forms.FlowLayoutPanel
    $buttons.Dock = 'Fill'
    $buttons.WrapContents = $false
    foreach ($entry in @(
        @('Терминал Linux', { Open-Terminal }),
        @('Запустить Ubuntu', { Start-Linux }),
        @('Состояние', { Start-Operation 'status' }),
        @('Службы Linux', { Start-Operation 'health' })
    )) {
        $button = New-Object System.Windows.Forms.Button
        $button.Text = $entry[0]
        $button.AutoSize = $true
        $button.Height = 34
        $button.Padding = New-Object System.Windows.Forms.Padding(8,0,8,0)
        $button.Add_Click($entry[1])
        [void]$buttons.Controls.Add($button)
    }
    $output = New-Object System.Windows.Forms.RichTextBox
    $output.Dock = 'Fill'
    $output.ReadOnly = $true
    $output.WordWrap = $false
    $output.Font = New-Object System.Drawing.Font('Consolas', 10)
    $output.BackColor = [System.Drawing.Color]::White
    $output.BorderStyle = 'None'
    $logBar = New-Object System.Windows.Forms.FlowLayoutPanel
    $logBar.Dock = 'Fill'
    $logLabel = New-Object System.Windows.Forms.Label
    $logLabel.Text = 'Контейнер:'
    $logLabel.AutoSize = $true
    $logLabel.Margin = New-Object System.Windows.Forms.Padding(0,8,6,0)
    $container = New-Object System.Windows.Forms.ComboBox
    $container.DropDownStyle = 'DropDownList'
    $container.Width = 260
    # Every container is populated from Docker, not a hardcoded project list.
    $logs = New-Object System.Windows.Forms.Button
    $logs.Text = 'Журнал'
    $logs.AutoSize = $true
    $logs.Add_Click({ Start-Operation 'logs' ([string]$container.SelectedItem) })
    $restartContainer = New-Object System.Windows.Forms.Button
    $restartContainer.Text = 'Перезапустить выбранный'
    $restartContainer.AutoSize = $true
    $restartContainer.Add_Click({ Confirm-Operation 'restart-container' "Перезапустить $($container.SelectedItem)?" ([string]$container.SelectedItem) })
    $startContainer = New-Object System.Windows.Forms.Button
    $startContainer.Text = 'Запустить'
    $startContainer.AutoSize = $true
    $startContainer.Add_Click({ Confirm-Operation 'start-container' "Запустить $($container.SelectedItem)?" ([string]$container.SelectedItem) })
    $stopContainer = New-Object System.Windows.Forms.Button
    $stopContainer.Text = 'Остановить'
    $stopContainer.AutoSize = $true
    $stopContainer.Add_Click({ Confirm-Operation 'stop-container' "Остановить $($container.SelectedItem)?" ([string]$container.SelectedItem) })
    $restartContainer.Text = 'Перезапустить'
    $container.Width = 220
    $logBar.Controls.AddRange(@($logLabel,$container,$logs,$startContainer,$stopContainer,$restartContainer))
    $layout.Controls.Add($title,0,0)
    $layout.Controls.Add($taskText,0,1)
    $layout.Controls.Add($buttons,0,2)
    $layout.Controls.Add($output,0,3)
    $layout.Controls.Add($logBar,0,4)
    $strip = New-Object System.Windows.Forms.StatusStrip
    $status = New-Object System.Windows.Forms.ToolStripStatusLabel
    $status.Text = 'Закрытие панели не выключает сервер'
    [void]$strip.Items.Add($status)
    $form.Controls.Add($layout)
    $form.Controls.Add($menu)
    $form.Controls.Add($strip)

    $timer = New-Object System.Windows.Forms.Timer
    $timer.Interval = 250
    $timer.Add_Tick({
        if ($null -ne $script:Work) {
            $work = $script:Work
            if ($work.Process.HasExited -and $work.Out.IsCompleted -and $work.Err.IsCompleted) {
                $code = $work.Process.ExitCode
                $script:LastExitCode = $code
                $text = $work.Out.Result + $work.Err.Result
                if ($work.Action -eq 'status' -and $text.Contains('__WSL_CONTAINER_NAMES__')) {
                    $sections = $text -split '__WSL_CONTAINER_NAMES__',2
                    $previous = [string]$container.SelectedItem
                    $container.Items.Clear()
                    foreach ($name in ($sections[1] -split '\r?\n')) {
                        if ($name -match '^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$') { [void]$container.Items.Add($name) }
                    }
                    if ($container.Items.Contains($previous)) { $container.SelectedItem=$previous }
                    elseif ($container.Items.Count) { $container.SelectedIndex=0 }
                    $text=$sections[0]
                }
                $output.Text = $text.Replace("`r`n","`n").Replace("`n","`r`n")
                $status.Text = if ($code -eq 0) { 'Готово: ' + $ActionNames[$work.Action] + ' · ' + (Get-Date -Format 'HH:mm:ss') } else { "Ошибка ($code). Подробности выше." }
                $taskText.Text = Get-TaskSummary
                $work.Process.Dispose()
                $script:Work = $null
                if ($work.Action -eq 'wsl-restart' -and $code -eq 0) { Start-Linux }
                if ($script:CloseAfterWork) { $form.Close(); return }
                if ($work.Action -in @('start-container','stop-container','restart-container') -and $code -eq 0) { $script:NextStatus = (Get-Date).AddSeconds(2) }
            } else {
                $elapsed = [int]((Get-Date) - $work.Started).TotalSeconds
                $status.Text = "$($ActionNames[$work.Action]): $elapsed сек. Панель отвечает, сервер работает отдельно."
            }
        } elseif ((Get-Date) -ge $script:NextStatus) {
            $script:NextStatus = [DateTime]::MaxValue
            Start-Operation 'status'
        }
    })
    $form.Add_Shown({
        $form.WindowState = 'Normal'
        $form.ShowInTaskbar = $true
        $form.TopMost = $true
        $form.Activate()
        $form.TopMost = $false
        Start-Linux
        $timer.Start()
    })
    $form.Add_FormClosing({
        if ($null -ne $script:Work) {
            # Finish an already requested Docker operation without a visible window.
            $_.Cancel = $true
            $script:CloseAfterWork = $true
            $form.Hide()
        }
    })
    $form.Add_FormClosed({
        $timer.Stop()
        $timer.Dispose()
        # Do not stop Task Scheduler or kill the WSL background host on close.
        if ($null -ne $script:Work) { $script:Work.Process.Dispose() }
    })
    if ($Check) {
        # CLI integration check: construct the real controls and run a read-only
        # WSL command through the same asynchronous path, without showing a window.
        Start-Operation 'status'
        $timer.Start()
        $deadline = (Get-Date).AddSeconds(25)
        while ($null -ne $script:Work -and (Get-Date) -lt $deadline) {
            [System.Windows.Forms.Application]::DoEvents()
            Start-Sleep -Milliseconds 30
        }
        if ($null -ne $script:Work) { throw 'Panel status check timed out.' }
        if ($script:LastExitCode -ne 0) { throw $output.Text }
        if ($output.Text -notmatch 'Linux:') { throw 'Linux status missing.' }
        @{ Result='passed'; WindowTitle=$form.Text; Task=(Get-TaskSummary); Status=$output.Text; Containers=@($container.Items) } | ConvertTo-Json -Compress
        $form.Close()
        $timer.Dispose()
    } else {
        [void]$form.ShowDialog()
    }
} catch {
    if ($Check) { [Console]::Error.WriteLine($_.ToString()); exit 1 }
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Linux / WSL — ошибка запуска', 'OK', 'Error') | Out-Null
    exit 1
}
