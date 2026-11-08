#!/bin/bash
# Подвійний клік у Finder: перевіряє найновіший .csv з папки input/ і відкриває звіт.
cd "$(dirname "$0")" || exit 1
bash check.sh
echo; read -n 1 -s -r -p "Натисніть будь-яку клавішу, щоб закрити…"
