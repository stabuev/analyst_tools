#!/usr/bin/env bash

set -eu

if [[ $# -ne 1 ]]; then
    printf 'usage: folder_summary.sh DIRECTORY\n' >&2
    exit 2
fi

folder=$1

if [[ ! -d "$folder" ]]; then
    printf 'folder-summary: directory does not exist: %s\n' "$folder" >&2
    exit 2
fi

printf '# Folder summary\n\n'
printf 'Folder: %s\n' "$folder"
file_count=$(find "$folder" -type f | wc -l)
printf 'Files: %d\n' "$file_count"
printf '\nCSV files:\n'
find "$folder" -type f -name '*.csv' | sort
