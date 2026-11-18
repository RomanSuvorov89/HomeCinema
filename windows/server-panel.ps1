param([switch]$Check)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

try {
    $Config = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'server-panel.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($Config.Distribution -notmatch '^[A-Za-z0-9_.-]+$') { throw 'Неверное имя дистрибутива WSL.' }
    $TaskName = 'HomeCinemaWsl-' + $Config.Distribution
    $WslPath = Join-Path $env:SystemRoot 'System32\wsl.exe'
    $Controller = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'wsl-server-control.sh') -Raw -Encoding UTF8
    $script:Work = $null
    $script:NextStatus = [DateTime]::MaxValue
    $script:CloseAfterWork = $false
    $ActionNames = @{status='Состояние сервера';start='Запуск сервера';stop='Остановка сервера';restart='Перезапуск сервера';health='Проверка сервисов';logs='Журнал контейнера';resources='Ресурсы контейнеров';disk='Использование диска';'restart-container'='Перезапуск контейнера'}

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
        [System.Windows.Forms.MessageBox]::Show($form, $Message, 'HomeCinema', 'OK', 'Error') | Out-Null
    }
    function Start-Operation([string]$Action, [string]$Target = '') {
        if ($null -ne $script:Work) { return }
        try {
            $taskText.Text = Get-TaskSummary
            $output.Text = "$($ActionNames[$Action])…`r`n"
            $status.Text = 'Работаем… Окно можно закрыть, сервер продолжит работать.'
            $info = New-Object System.Diagnostics.ProcessStartInfo
            $info.FileName = $WslPath
            $parts = @('--distribution', [string]$Config.Distribution, '--exec', 'bash', '-s', '--', $Action, [string]$Config.RepositoryPath, $Target)
            $info.Arguments = ($parts | ForEach-Object { Quote-Argument $_ }) -join ' '
            $info.UseShellExecute = $false
            $info.CreateNoWindow = $true
            $info.RedirectStandardInput = $true
            $info.RedirectStandardOutput = $true
            $info.RedirectStandardError = $true
            $info.StandardOutputEncoding = [System.Text.Encoding]::UTF8
            $info.StandardErrorEncoding = [System.Text.Encoding]::UTF8
            $process = [System.Diagnostics.Process]::Start($info)
            $outTask = $process.StandardOutput.ReadToEndAsync()
            $errTask = $process.StandardError.ReadToEndAsync()
            $process.StandardInput.Write($Controller.Replace("`r`n", "`n"))
            $process.StandardInput.Close()
            $script:Work = @{ Process=$process; Out=$outTask; Err=$errTask; Action=$Action; Started=Get-Date }
        } catch { $status.Text = 'Не удалось выполнить действие'; Show-Error $_.Exception.Message }
    }
    function Start-Server {
        try { Ensure-Background; Start-Operation 'start' }
        catch { Show-Error $_.Exception.Message }
    }
    function Confirm-Operation([string]$Action, [string]$Message, [string]$Target = '') {
        if ($null -ne $script:Work) { return }
        if ([System.Windows.Forms.MessageBox]::Show($form, $Message, 'HomeCinema', 'YesNo', 'Question') -eq 'Yes') {
            Start-Operation $Action $Target
        }
    }
    function Open-Lampa {
        try {
            $uri = [Uri]$Config.ServerUrl
            if ($uri.Scheme -notin @('http','https')) { throw 'Неверный адрес Лампы.' }
            Start-Process -FilePath $uri.AbsoluteUri | Out-Null
        } catch { Show-Error $_.Exception.Message }
    }

    $form = New-Object System.Windows.Forms.Form
    $form.Text = 'HomeCinema — управление сервером'
    $form.Size = New-Object System.Drawing.Size(1080, 760)
    $form.MinimumSize = New-Object System.Drawing.Size(800, 560)
    $form.StartPosition = 'CenterScreen'
    $form.Font = New-Object System.Drawing.Font('Segoe UI', 10)
    $form.BackColor = [System.Drawing.Color]::FromArgb(245,247,250)

    $menu = New-Object System.Windows.Forms.MenuStrip
    $serverMenu = $menu.Items.Add('Сервер')
    $startItem = $serverMenu.DropDownItems.Add('Запустить HomeCinema')
    $startItem.Add_Click({ Start-Server })
    $stopItem = $serverMenu.DropDownItems.Add('Остановить HomeCinema')
    $stopItem.Add_Click({ Confirm-Operation 'stop' 'Остановить контейнеры HomeCinema? Данные сохранятся. Другие проекты Docker продолжат работать.' })
    $restartItem = $serverMenu.DropDownItems.Add('Перезапустить HomeCinema')
    $restartItem.Add_Click({ Confirm-Operation 'restart' 'Перезапустить контейнеры HomeCinema? Текущее воспроизведение может прерваться.' })
    $viewMenu = $menu.Items.Add('Просмотр')
    $stateItem = $viewMenu.DropDownItems.Add('Состояние и контейнеры')
    $stateItem.Add_Click({ Start-Operation 'status' })
    $healthItem = $viewMenu.DropDownItems.Add('Проверить доступность сервисов')
    $healthItem.Add_Click({ Start-Operation 'health' })
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
    $aboutItem.Add_Click({ [System.Windows.Forms.MessageBox]::Show($form, "Ярлык запускает сервер и открывает панель.`r`nЗакрытие панели НЕ выключает сервер.`r`nОстановка через меню затрагивает только HomeCinema.`r`nФоновая задача WSL работает отдельно и восстанавливается каждые 5 минут.`r`n`r`nWSL: $($Config.Distribution)`r`nПроект: $($Config.RepositoryPath)`r`nЛампа: $($Config.ServerUrl)", 'HomeCinema') | Out-Null })
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
    $title.Text = 'HomeCinema'
    $title.Font = New-Object System.Drawing.Font('Segoe UI', 21, [System.Drawing.FontStyle]::Bold)
    $title.Dock = 'Fill'
    $taskText = New-Object System.Windows.Forms.Label
    $taskText.Dock = 'Fill'
    $taskText.Text = 'Проверяем фоновый запуск…'
    $buttons = New-Object System.Windows.Forms.FlowLayoutPanel
    $buttons.Dock = 'Fill'
    $buttons.WrapContents = $false
    foreach ($entry in @(
        @('Открыть Лампу', { Open-Lampa }),
        @('Запустить', { Start-Server }),
        @('Состояние', { Start-Operation 'status' }),
        @('Проверить сервисы', { Start-Operation 'health' })
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
    foreach ($name in @('home-cinema-lampac','home-cinema-recommender','home-cinema-posters','home-cinema-torrserver')) { [void]$container.Items.Add($name) }
    $container.SelectedIndex = 0
    $logs = New-Object System.Windows.Forms.Button
    $logs.Text = 'Журнал'
    $logs.AutoSize = $true
    $logs.Add_Click({ Start-Operation 'logs' ([string]$container.SelectedItem) })
    $restartContainer = New-Object System.Windows.Forms.Button
    $restartContainer.Text = 'Перезапустить выбранный'
    $restartContainer.AutoSize = $true
    $restartContainer.Add_Click({ Confirm-Operation 'restart-container' "Перезапустить $($container.SelectedItem)?" ([string]$container.SelectedItem) })
    $logBar.Controls.AddRange(@($logLabel,$container,$logs,$restartContainer))
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
                $output.Text = $text.Replace("`r`n","`n").Replace("`n","`r`n")
                $status.Text = if ($code -eq 0) { 'Готово: ' + $ActionNames[$work.Action] + ' · ' + (Get-Date -Format 'HH:mm:ss') } else { "Ошибка ($code). Подробности выше." }
                $taskText.Text = Get-TaskSummary
                $work.Process.Dispose()
                $script:Work = $null
                if ($script:CloseAfterWork) { $form.Close(); return }
                if ($work.Action -eq 'start' -and $code -eq 0) { $script:NextStatus = (Get-Date).AddSeconds(2) }
            } else {
                $elapsed = [int]((Get-Date) - $work.Started).TotalSeconds
                $status.Text = "$($ActionNames[$work.Action]): $elapsed сек. Панель отвечает, сервер работает отдельно."
            }
        } elseif ((Get-Date) -ge $script:NextStatus) {
            $script:NextStatus = [DateTime]::MaxValue
            Start-Operation 'status'
        }
    })
    $form.Add_Shown({ Start-Server; $timer.Start() })
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
        if ($output.Text -notmatch 'home-cinema-lampac') { throw 'Container list missing from panel status.' }
        @{ Result='passed'; WindowTitle=$form.Text; Task=(Get-TaskSummary); Status=$output.Text } | ConvertTo-Json -Compress
        $form.Close()
        $timer.Dispose()
    } else {
        [void]$form.ShowDialog()
    }
} catch {
    if ($Check) { [Console]::Error.WriteLine($_.ToString()); exit 1 }
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'HomeCinema — ошибка запуска', 'OK', 'Error') | Out-Null
    exit 1
}
