#!/usr/bin/env bash

set -euo pipefail
export LC_ALL=C

usage() {
    cat <<'EOF'
Usage:
  file_audit.sh [--top N] [--output FILE] DIRECTORY

Build a deterministic Markdown report for regular files under DIRECTORY.
The .git directory is excluded. If FILE is inside DIRECTORY, it is excluded too.

Options:
  --top N        Show N largest files (default: 10)
  --output FILE  Write the report atomically instead of printing it
  -h, --help     Show this help
EOF
}

fail() {
    printf 'file-audit: %s\n' "$1" >&2
    exit 2
}

top=10
output=
root_argument=

while (($# > 0)); do
    case "$1" in
        --top)
            (($# >= 2)) || fail "--top requires a positive integer"
            top=$2
            shift 2
            ;;
        --output)
            (($# >= 2)) || fail "--output requires a file path"
            output=$2
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            (($# == 1)) || fail "expected exactly one directory after --"
            [[ -z "$root_argument" ]] || fail "expected exactly one directory"
            root_argument=$1
            shift
            ;;
        -*)
            fail "unknown option: $1"
            ;;
        *)
            [[ -z "$root_argument" ]] || fail "expected exactly one directory"
            root_argument=$1
            shift
            ;;
    esac
done

[[ "$top" =~ ^[1-9][0-9]*$ ]] || fail "--top must be a positive integer"
[[ -n "$root_argument" ]] || fail "directory is required"
[[ -d "$root_argument" ]] || fail "directory does not exist: $root_argument"

root=$(cd -- "$root_argument" && pwd -P)
output_absolute=

if [[ -n "$output" ]]; then
    [[ ! -d "$output" ]] || fail "output path is a directory: $output"
    output_directory=$(dirname -- "$output")
    output_name=$(basename -- "$output")
    [[ -d "$output_directory" ]] || fail "output directory does not exist: $output_directory"
    output_directory=$(cd -- "$output_directory" && pwd -P)
    output_absolute="$output_directory/$output_name"
fi

paths=$(mktemp "${TMPDIR:-/tmp}/file-audit-paths.XXXXXX")
records=$(mktemp "${TMPDIR:-/tmp}/file-audit-records.XXXXXX")
report=$(mktemp "${TMPDIR:-/tmp}/file-audit-report.XXXXXX")

cleanup() {
    rm -f -- "$paths" "$records" "$report"
}
trap cleanup EXIT

file_count=0
total_bytes=0

find "$root" -type d -name .git -prune -o -type f -print0 > "$paths"

while IFS= read -r -d '' file; do
    if [[ -n "$output_absolute" && "$file" == "$output_absolute" ]]; then
        continue
    fi

    bytes=$(wc -c < "$file")
    bytes=${bytes//[[:space:]]/}
    relative=${file#"$root"/}
    quoted_path=$(printf '%q' "$relative")
    name=${relative##*/}

    if [[ "$name" == *.* && "$name" != .* ]] || [[ "$name" == .*.* ]]; then
        extension=${name##*.}
    else
        extension="[none]"
    fi
    if [[ "$extension" != "[none]" ]]; then
        extension=$(printf '%s' "$extension" | tr '[:upper:]' '[:lower:]')
        if [[ ! "$extension" =~ ^[a-z0-9][a-z0-9_+-]*$ ]]; then
            extension="[other]"
        fi
    fi

    printf '%s\t%s\t%s\n' "$bytes" "$quoted_path" "$extension" >> "$records"
    file_count=$((file_count + 1))
    total_bytes=$((total_bytes + bytes))
done < "$paths"

root_label=$(printf '%q' "$root_argument")

{
    printf '# File audit\n\n'
    printf -- '- Root: `%s`\n' "$root_label"
    printf -- '- Files: %s\n' "$file_count"
    printf -- '- Bytes: %s\n' "$total_bytes"
    printf '\n## Largest files\n\n'
    printf '| Bytes | Path |\n'
    printf '|---:|---|\n'
    if ((file_count == 0)); then
        printf '| 0 | _No regular files_ |\n'
    else
        sort -t $'\t' -k1,1nr -k2,2 "$records" |
            awk -F '\t' -v limit="$top" \
                'NR <= limit { printf "| %s | `%s` |\n", $1, $2 }'
    fi
    printf '\n## Extensions\n\n'
    printf '| Extension | Files |\n'
    printf '|---|---:|\n'
    if ((file_count == 0)); then
        printf '| `[none]` | 0 |\n'
    else
        cut -f3 "$records" |
            sort |
            uniq -c |
            sort -k1,1nr -k2,2 |
            awk '{ printf "| `%s` | %s |\n", $2, $1 }'
    fi
} > "$report"

if [[ -n "$output_absolute" ]]; then
    mv -- "$report" "$output_absolute"
    printf 'file-audit: wrote %s\n' "$output_absolute" >&2
else
    cat "$report"
fi
