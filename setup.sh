#!/usr/bin/env sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python3 -m pip install "$project_dir"
if [ "$#" -gt 0 ]; then
    python3 -m research_loop_kit init "$1" --wizard
else
    printf '%s\n' 'インストールしました。python3 -m research_loop_kit init <空の研究フォルダ> --wizard で開始できます。'
fi
