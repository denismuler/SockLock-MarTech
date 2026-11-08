#!/bin/bash
# Перевірка таблиці одним запуском.
#   bash check.sh                 -> бере найновіший .csv з папки input/
#   bash check.sh шлях/файл.csv   -> бере вказаний файл
# Додаткові параметри (--steps, --focus, --min-n …) передаються далі: bash check.sh файл.csv --min-n 30
cd "$(dirname "$0")" || exit 1
PY=python3; [ -x .venv/bin/python ] && PY=.venv/bin/python

if [ -n "$1" ] && [ "${1#--}" = "$1" ]; then
  FILE="$1"; shift
else
  FILE=$(ls -t input/*.csv 2>/dev/null | head -1)
  if [ -z "$FILE" ]; then
    echo "Немає таблиці. Покладіть .csv у папку input/ і запустіть ще раз."; exit 1
  fi
fi
[ -f "$FILE" ] || { echo "Файл не знайдено: $FILE"; exit 1; }

NAME=$(basename "$FILE" .csv)
echo "Перевіряю: $FILE"
if $PY -m quizleak "$FILE" --out "out/$NAME" "$@"; then
  echo "Готово. Звіт: out/$NAME/report.html"
  open "out/$NAME/report.html" 2>/dev/null || true
fi
