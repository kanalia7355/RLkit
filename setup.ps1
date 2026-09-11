param([string]$Workspace = "")
$ErrorActionPreference = 'Stop'
python -m pip install $PSScriptRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($Workspace) {
    python -m research_loop_kit init $Workspace --wizard
    exit $LASTEXITCODE
}
Write-Output 'インストールしました。空の研究フォルダを指定して python -m research_loop_kit init <フォルダ> --wizard を実行してください。'
