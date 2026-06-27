@echo off
setlocal
set "EXPORT_CONTEXT_BAT=%~f0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $bat=$env:EXPORT_CONTEXT_BAT; $raw=Get-Content -LiteralPath $bat -Raw; $payload=($raw -split '# POWERSHELL_PAYLOAD\r?\n',2)[1]; Invoke-Expression $payload"
exit /b %ERRORLEVEL%
# POWERSHELL_PAYLOAD

$ErrorActionPreference = "Stop"

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message"
}

function Write-WarnLine {
    param([string]$Message)
    Write-Host "[WARN] $Message"
}

function Get-ContextRelativePath {
    param(
        [string]$BasePath,
        [string]$FullPath
    )

    $base = [System.IO.Path]::GetFullPath($BasePath)
    $target = [System.IO.Path]::GetFullPath($FullPath)

    if (-not $base.EndsWith([System.IO.Path]::DirectorySeparatorChar)) {
        $base = $base + [System.IO.Path]::DirectorySeparatorChar
    }

    $baseUri = New-Object System.Uri($base)
    $targetUri = New-Object System.Uri($target)
    return [System.Uri]::UnescapeDataString($baseUri.MakeRelativeUri($targetUri).ToString()) -replace "/", [System.IO.Path]::DirectorySeparatorChar
}

function Test-ExcludedRelativePath {
    param([string]$RelativePath)

    $normalized = $RelativePath -replace "\\", "/"
    $name = Split-Path -Path $normalized -Leaf

    $excludedDirectories = @(
        ".git",
        "export",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".venv",
        ".repoanalyzer-index"
    )

    foreach ($directory in $excludedDirectories) {
        if ($normalized -eq $directory -or $normalized.StartsWith("$directory/") -or $normalized.Contains("/$directory/")) {
            return $true
        }
    }

    if ($name -like "*.pyc") { return $true }
    if ($name -like ".env*") { return $true }

    $secretNamePatterns = @("*secret*", "*token*", "*credential*", "*password*", "*key*")
    foreach ($pattern in $secretNamePatterns) {
        if ($name -like $pattern) {
            return $true
        }
    }

    return $false
}

function Copy-ContextItem {
    param(
        [string]$SourceRoot,
        [string]$RelativePath,
        [string]$DestinationRoot
    )

    $source = Join-Path $SourceRoot $RelativePath
    if (-not (Test-Path -LiteralPath $source)) {
        Write-WarnLine "Skipping missing optional item: $RelativePath"
        return
    }

    $sourceItem = Get-Item -LiteralPath $source -Force
    if ($sourceItem.PSIsContainer) {
        Get-ChildItem -LiteralPath $sourceItem.FullName -Recurse -File -Force | ForEach-Object {
            $relativeFile = Get-ContextRelativePath -BasePath $SourceRoot -FullPath $_.FullName
            if (Test-ExcludedRelativePath $relativeFile) {
                return
            }

            $destination = Join-Path $DestinationRoot $relativeFile
            $destinationDirectory = Split-Path -Path $destination -Parent
            New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $destination -Force
        }
    }
    else {
        if (Test-ExcludedRelativePath $RelativePath) {
            Write-WarnLine "Skipping excluded file: $RelativePath"
            return
        }

        $destination = Join-Path $DestinationRoot $RelativePath
        $destinationDirectory = Split-Path -Path $destination -Parent
        New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
        Copy-Item -LiteralPath $sourceItem.FullName -Destination $destination -Force
    }
}

function Invoke-OptionalCommand {
    param(
        [string]$Command,
        [string[]]$Arguments,
        [string]$WorkingDirectory,
        [string]$UnavailableMessage
    )

    $commandInfo = Get-Command $Command -ErrorAction SilentlyContinue
    if (-not $commandInfo) {
        return $UnavailableMessage
    }

    $originalLocation = Get-Location
    try {
        Set-Location -LiteralPath $WorkingDirectory
        $output = & $Command @Arguments 2>&1
        if ($LASTEXITCODE -ne 0) {
            return "$Command exited with code $LASTEXITCODE`r`n$output"
        }
        if ($null -eq $output) {
            return ""
        }
        return ($output | Out-String)
    }
    catch {
        return "$Command failed: $($_.Exception.Message)"
    }
    finally {
        Set-Location -LiteralPath $originalLocation
    }
}

$batPath = [System.IO.Path]::GetFullPath($env:EXPORT_CONTEXT_BAT)
$toolDir = Split-Path -Path $batPath -Parent
$repoRoot = Split-Path -Path $toolDir -Parent
$exportDir = Join-Path $repoRoot "export"

$requiredItems = @(
    "repoanalyzer",
    "docs",
    "tests",
    "pyproject.toml",
    "README.md"
)

$optionalItems = @(
    "attic/reference",
    "memo.md",
    ".gitignore",
    "tool/export_chatgpt_context.bat"
)

$missingRequired = @()
foreach ($item in $requiredItems) {
    if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $item))) {
        $missingRequired += $item
    }
}

if ($missingRequired.Count -gt 0) {
    Write-Error "Required item(s) missing: $($missingRequired -join ', ')"
    exit 1
}

New-Item -ItemType Directory -Path $exportDir -Force | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$zipName = "repoanalyzer-chatgpt-context-$timestamp.zip"
$zipPath = Join-Path $exportDir $zipName
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "repoanalyzer-chatgpt-context-$timestamp-$PID"
$stagingRoot = Join-Path $tempRoot "repoanalyzer-chatgpt-context"

Write-Info "Repo root: $repoRoot"
Write-Info "Staging: $stagingRoot"
Write-Info "Output: $zipPath"

try {
    New-Item -ItemType Directory -Path $stagingRoot -Force | Out-Null

    foreach ($item in ($requiredItems + $optionalItems)) {
        Copy-ContextItem -SourceRoot $repoRoot -RelativePath $item -DestinationRoot $stagingRoot
    }

    $treeLines = Get-ChildItem -LiteralPath $stagingRoot -Recurse -File -Force |
        Sort-Object FullName |
        ForEach-Object { (Get-ContextRelativePath -BasePath $stagingRoot -FullPath $_.FullName) -replace "\\", "/" }

    Set-Content -LiteralPath (Join-Path $stagingRoot "REPO_TREE.txt") -Value $treeLines -Encoding UTF8

    $gitStatus = Invoke-OptionalCommand `
        -Command "git" `
        -Arguments @("status", "--short", "--ignored") `
        -WorkingDirectory $repoRoot `
        -UnavailableMessage "git unavailable"
    Set-Content -LiteralPath (Join-Path $stagingRoot "GIT_STATUS.txt") -Value $gitStatus -Encoding UTF8

    $gitDiff = Invoke-OptionalCommand `
        -Command "git" `
        -Arguments @("diff", "--no-ext-diff", "--binary") `
        -WorkingDirectory $repoRoot `
        -UnavailableMessage "git unavailable"
    Set-Content -LiteralPath (Join-Path $stagingRoot "GIT_DIFF.patch") -Value $gitDiff -Encoding UTF8

    $pythonVersion = Invoke-OptionalCommand -Command "python" -Arguments @("--version") -WorkingDirectory $repoRoot -UnavailableMessage "python unavailable"
    $pytestVersion = Invoke-OptionalCommand -Command "pytest" -Arguments @("--version") -WorkingDirectory $repoRoot -UnavailableMessage "pytest unavailable"
    $gitVersion = Invoke-OptionalCommand -Command "git" -Arguments @("--version") -WorkingDirectory $repoRoot -UnavailableMessage "git unavailable"

    $environment = @(
        "CreatedAt: $(Get-Date -Format o)",
        "RepoRoot: $repoRoot",
        "BatPath: $batPath",
        "OutputZip: $zipPath",
        "",
        "[Tools]",
        "PowerShell: $($PSVersionTable.PSVersion)",
        "Python: $($pythonVersion.Trim())",
        "Pytest: $($pytestVersion.Trim())",
        "Git: $($gitVersion.Trim())"
    )
    Set-Content -LiteralPath (Join-Path $stagingRoot "ENVIRONMENT.txt") -Value $environment -Encoding UTF8

    $context = @"
# repoanalyzer ChatGPT Context

This archive contains the source and supporting context needed to discuss repoanalyzer design and implementation with ChatGPT.

## Project Purpose

repoanalyzer is a C/C++ Code Evidence Engine for MCP-based LLM agents. Its current MVP focuses on typed, source-grounded evidence from C/C++ repositories.

## Included

- `repoanalyzer/`: Python package source.
- `tests/`: pytest tests and C/C++ fixtures.
- `docs/`: design and contract documents.
- `attic/reference/`: older reference implementation useful for design comparison.
- Root project files: `README.md`, `memo.md`, `pyproject.toml`, `.gitignore`.
- `tool/export_chatgpt_context.bat`: the export tool that created this archive.
- Generated context files: `REPO_TREE.txt`, `GIT_STATUS.txt`, `GIT_DIFF.patch`, `ENVIRONMENT.txt`.

## Excluded

The archive intentionally excludes Git internals, export output, caches, virtual environments, generated indexes, Python bytecode, `.env*` files, and filenames that look like secrets, tokens, credentials, passwords, or keys.

## Suggested ChatGPT Prompt

Use this archive as the complete working context for repoanalyzer. Start from `README.md`, `memo.md`, `docs/`, and `pyproject.toml`, then inspect `repoanalyzer/` and `tests/` before proposing design or implementation changes. Treat `attic/reference/` as historical reference, not active source.
"@
    Set-Content -LiteralPath (Join-Path $stagingRoot "CHATGPT_CONTEXT.md") -Value $context -Encoding UTF8

    if (Test-Path -LiteralPath $zipPath) {
        Write-Error "Output already exists unexpectedly: $zipPath"
        exit 1
    }

    Compress-Archive -Path (Join-Path $stagingRoot "*") -DestinationPath $zipPath -CompressionLevel Optimal -Force

    $zipItem = Get-Item -LiteralPath $zipPath
    $fileCount = (Get-ChildItem -LiteralPath $stagingRoot -Recurse -File -Force | Measure-Object).Count
    $zipSizeKiB = [Math]::Round($zipItem.Length / 1KB, 1)

    Write-Host ""
    Write-Host "Created ZIP: $zipPath"
    Write-Host "Files: $fileCount"
    Write-Host "Size: $zipSizeKiB KiB"
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
