$ErrorActionPreference = 'Stop'
$taskEnvPath = Join-Path $PSScriptRoot '../.env'
if (-not (Test-Path -LiteralPath $taskEnvPath)) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot '../.env.example') -Destination $taskEnvPath
}
$taskEnvText = [IO.File]::ReadAllText($taskEnvPath)
if ($taskEnvText -notmatch '(?m)^APP_USERNAME=.+$') {
    $taskEnvText = [regex]::Replace($taskEnvText, '(?m)^APP_USERNAME=.*\r?\n?', '')
    $taskEnvText += "`nAPP_USERNAME=localadmin`n"
}
if ($taskEnvText -notmatch '(?m)^APP_PASSWORD=.+$') {
    $taskPasswordBytes = [byte[]]::new(32)
    [Security.Cryptography.RandomNumberGenerator]::Fill($taskPasswordBytes)
    $taskPassword = [Convert]::ToBase64String($taskPasswordBytes)
    $taskEnvText = [regex]::Replace($taskEnvText, '(?m)^APP_PASSWORD=.*\r?\n?', '')
    $taskEnvText += "APP_PASSWORD=$taskPassword`n"
}
[IO.File]::WriteAllText($taskEnvPath, $taskEnvText)
Write-Output 'Local access credentials are configured in .env. Existing credentials were preserved.'
