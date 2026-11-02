[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$repoRoot = (git rev-parse --show-toplevel).Trim()
Set-Location -LiteralPath $repoRoot

Write-Host "Repositorio: $repoRoot"

# git status nao mostra ficheiros com skip-worktree. Fazemos uma copia
# temporaria deles para que um pull nunca substitua personalizacoes locais
# silenciosamente (por exemplo, o 06-cover-letter-templates.md).
$protectedRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("ai-job-search-pre-pull-" + [guid]::NewGuid().ToString('N'))
$protectedFiles = @()
$skipWorktreeEntries = @(git ls-files -v | Where-Object { $_ -cmatch '^S ' })
foreach ($entry in $skipWorktreeEntries) {
    $relative = $entry.Substring(2)
    if ([string]::IsNullOrWhiteSpace($relative)) { continue }
    $source = Join-Path $repoRoot $relative
    if (Test-Path -LiteralPath $source -PathType Leaf) {
        $destination = Join-Path $protectedRoot $relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination -Force
        $protectedFiles += $relative
    }
}

function Restore-ProtectedFiles {
    foreach ($relative in $protectedFiles) {
        $backup = Join-Path $protectedRoot $relative
        $destination = Join-Path $repoRoot $relative
        if (Test-Path -LiteralPath $backup -PathType Leaf) {
            Copy-Item -LiteralPath $backup -Destination $destination -Force
            git update-index --skip-worktree -- "$relative"
        }
    }
    if (Test-Path -LiteralPath $protectedRoot) {
        Remove-Item -LiteralPath $protectedRoot -Recurse -Force
    }
}

function Prepare-ProtectedFilesForPull {
    foreach ($relative in $protectedFiles) {
        # Depois de a copia de seguranca existir, removemos temporariamente
        # o marcador e repomos a versao do indice. Caso contrario, o pull
        # ainda ve a personalizacao local e recusa atualizar esse ficheiro.
        git update-index --no-skip-worktree -- "$relative"
        if ($LASTEXITCODE -ne 0) { throw "Nao foi possivel preparar $relative para o pull." }
        git checkout -- "$relative"
        if ($LASTEXITCODE -ne 0) { throw "Nao foi possivel limpar temporariamente $relative para o pull." }
    }
}

if ($protectedFiles.Count -gt 0) {
    Write-Host "Protegidos $($protectedFiles.Count) ficheiros skip-worktree para o pull."
}

Prepare-ProtectedFilesForPull

$status = git status --porcelain
$stashCreated = $false
$stashPopped = $false
$stashRef = $null

if ($status) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $message = "pre-pull automatico $stamp"
    Write-Host "A guardar alteracoes locais..."
    git stash push --include-untracked --message $message
    if ($LASTEXITCODE -ne 0) { throw "Nao foi possivel criar o stash." }
    $stashCreated = $true
    $stashRef = (git stash list -1 --format='%gd').Trim()
    Write-Host "Guardado em $stashRef"
} else {
    Write-Host "Nao existem alteracoes locais para guardar."
}

try {
    Write-Host "A executar git pull --ff-only..."
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw "O git pull falhou." }

    if ($stashCreated) {
        Write-Host "A reaplicar $stashRef..."
        git stash pop $stashRef
        if ($LASTEXITCODE -ne 0) {
            # Em conflito, o git stash pop APPLICA e MANTEM o stash - as
            # alteracoes estao na arvore (com marcadores de conflito) e o
            # stash sobrevive para recuperacao.
            Write-Warning "A reaplicacao encontrou conflitos: as alteracoes estao na arvore (com marcadores de conflito) e o stash foi mantido. Resolve os conflitos e faz 'git stash drop' - o teste tests/test_pre_pull_stash_hygiene.py falha enquanto o stash estiver esquecido ha mais de 24h."
            Restore-ProtectedFiles
            exit 2
        }
        $stashPopped = $true
        Write-Host "Alteracoes locais reaplicadas com sucesso."
    }

    Restore-ProtectedFiles
    Write-Host "Concluido."
} catch {
    $failure = $_
    if ($stashCreated -and -not $stashPopped) {
        # O pull falhou: as alteracoes locais nao podem ficar presas no
        # stash (foi assim que um dia inteiro de trabalho ficou esquecido
        # em stash@{0} a 2026-09-05). Reaplicar em best-effort.
        Write-Warning "A reaplicar $stashRef apesar do pull falhado (as tuas alteracoes nao podem ficar presas no stash)..."
        git stash pop $stashRef
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Conflitos na reaplicacao: o stash foi MANTIDO pelo git. Resolve os conflitos e faz 'git stash drop'. O teste tests/test_pre_pull_stash_hygiene.py falha enquanto o stash estiver esquecido ha mais de 24h."
            Restore-ProtectedFiles
            exit 2
        }
        Write-Host "Alteracoes locais reaplicadas apesar do pull falhado. Re-executa o pull quando quiseres."
    }
    Restore-ProtectedFiles
    Write-Error -ErrorAction Continue $failure
    exit 1
}
