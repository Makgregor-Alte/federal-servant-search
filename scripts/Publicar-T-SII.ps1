# T. SII - publicação segura de alterações posteriores no GitHub.
# Exemplos:
#   powershell -ExecutionPolicy Bypass -File .\scripts\Publicar-T-SII.ps1 -Mensagem "fix(api): corrige filtros"
#   powershell -ExecutionPolicy Bypass -File .\scripts\Publicar-T-SII.ps1 -SemPush
[CmdletBinding()]
param(
    [string]$Mensagem = 'chore(integration): atualiza implementacao validada',
    [switch]$SemPush
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
function Confere($Nome) {
    if ($LASTEXITCODE -ne 0) { throw "Falha na etapa: $Nome (codigo $LASTEXITCODE)" }
}
$root = (& git rev-parse --show-toplevel)
Confere 'localizar o repositorio Git'
$root = ($root | Select-Object -First 1).Trim()
$branch = (& git -C $root branch --show-current)
Confere 'identificar branch'
$branch = ($branch | Select-Object -First 1).Trim()
if ($branch -notmatch '^feat/integration-takeover-[a-zA-Z0-9_-]+$') {
    throw "Recusado: branch atual '$branch'. Este script so publica a branch isolada de takeover."
}
$remote = (& git -C $root remote get-url origin)
Confere 'verificar remoto'
if ((($remote | Select-Object -First 1).Trim()) -notmatch '(?i)github[.]com[:/]Makgregor-Alte/federal-servant-search(?:[.]git)?$') {
    throw 'Remote origin inesperado; nenhuma alteracao publicada.'
}
Push-Location $root
try {
    & git diff --check
    Confere 'validar diferencas de codigo'
    # Testes Python rodam no container, sem exigir instalacao de Python no host.
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker CLI nao encontrado.' }
    & docker compose config --quiet
    Confere 'validar docker compose'
    & docker compose run -T --rm --no-deps --build --volume "${root}:/workspace" -w /workspace -e 'PYTHONPATH=/workspace/backend' backend python -m unittest discover -s backend/tests -v
    Confere '13 testes unitarios Python'
    # O build do frontend e feito por Docker; nao requer Node no host.
    & docker compose build frontend
    Confere 'compilar frontend React'
    & git add -A
    Confere 'preparar arquivos para commit'
    $staged = & git diff --cached --name-only
    Confere 'verificar staging'
    if (@($staged).Count -gt 0 -and -not [string]::IsNullOrWhiteSpace(($staged -join ''))) {
        & git diff --cached --check
        Confere 'validar staging'
        & git commit -m $Mensagem
        Confere 'criar commit'
    } else {
        Write-Host 'Sem mudancas novas: nenhum commit artificial foi criado.'
    }
    if (-not $SemPush) {
        & git push -u origin $branch
        Confere 'publicar branch isolada no GitHub'
        Write-Host "Publicado: $branch" -ForegroundColor Green
    } else {
        Write-Host 'Validacao concluida; push omitido por -SemPush.' -ForegroundColor Yellow
    }
} finally {
    Pop-Location
}
