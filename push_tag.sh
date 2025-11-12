#!/usr/bin/env bash
set -euo pipefail

ENV_FILE=".env"
KEY="CURRENT_APP_VERSION"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Unable to find ${ENV_FILE} in $(pwd)" >&2
  exit 1
fi

current_version="$(grep -E "^${KEY}=" "${ENV_FILE}" | tail -n1 | cut -d'=' -f2-)"
if [[ -z "${current_version}" ]]; then
  echo "Missing ${KEY} value in ${ENV_FILE}" >&2
  exit 1
fi

if [[ "${current_version}" != *.* ]]; then
  echo "Version \"${current_version}\" does not contain a '.' to increment." >&2
  exit 1
fi

base_part="${current_version%.*}"
patch_part="${current_version##*.}"

if ! [[ "${patch_part}" =~ ^[0-9]+$ ]]; then
  echo "Patch segment \"${patch_part}\" is not numeric." >&2
  exit 1
fi

next_patch=$((patch_part + 1))
next_version="${base_part}.${next_patch}"

tmp_file="$(mktemp)"
trap 'rm -f "${tmp_file}"' EXIT

awk -v key="${KEY}" -v new="${next_version}" '
  BEGIN { updated = 0 }
  $0 ~ "^"key"=" {
    print key"="new
    updated = 1
    next
  }
  { print }
  END {
    if (!updated) {
      print "Missing "key" entry" > "/dev/stderr"
      exit 1
    }
  }
' "${ENV_FILE}" > "${tmp_file}"

mv "${tmp_file}" "${ENV_FILE}"
trap - EXIT

echo "Tagging ${next_version} (was ${current_version})"
git tag "${next_version}"
git push --tags
