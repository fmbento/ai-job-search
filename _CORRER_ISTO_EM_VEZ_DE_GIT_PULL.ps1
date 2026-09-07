[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$repoRoot = (git rev-parse --show-toplevel).Trim()
Set-Location -LiteralPath $repoRoot

Write-Host "Repositorio: $repoRoot"

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
            exit 2
        }
        $stashPopped = $true
        Write-Host "Alteracoes locais reaplicadas com sucesso."
    }

    Write-Host "Concluido."
} catch {
    Write-Error $_
    if ($stashCreated -and -not $stashPopped) {
        # O pull falhou: as alteracoes locais nao podem ficar presas no
        # stash (foi assim que um dia inteiro de trabalho ficou esquecido
        # em stash@{0} a 2026-09-05). Reaplicar em best-effort.
        Write-Warning "A reaplicar $stashRef apesar do pull falhado (as tuas alteracoes nao podem ficar presas no stash)..."
        git stash pop $stashRef
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Conflitos na reaplicacao: o stash foi MANTIDO pelo git. Resolve os conflitos e faz 'git stash drop'. O teste tests/test_pre_pull_stash_hygiene.py falha enquanto o stash estiver esquecido ha mais de 24h."
            exit 2
        }
        Write-Host "Alteracoes locais reaplicadas apesar do pull falhado. Re-executa o pull quando quiseres."
    }
    exit 1
}
