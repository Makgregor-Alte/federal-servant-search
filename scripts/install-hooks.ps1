$ErrorActionPreference = 'Stop'
$root = (git rev-parse --show-toplevel).Trim()
if (-not $root) { throw 'Execute este script dentro do repositório Git.' }
Push-Location $root
try {
    if (-not (Test-Path '.githooks/post-commit')) { throw 'Copie .githooks antes de instalar.' }
    git config --local core.hooksPath .githooks
    Write-Host 'Hooks Git ativados: testes antes de push; push automatico apos commit em feature branches.'
    Write-Host 'Para desativar: git config --local --unset core.hooksPath'
} finally { Pop-Location }
