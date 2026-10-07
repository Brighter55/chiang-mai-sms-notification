#!/usr/bin/env sh
#
# Run on every deploy, before the app serves traffic.
#
# This exists because of an outage. The Google-review feature added a table the
# *order list* correlates against, so a database that was behind the code made
# every dashboard order fetch return 500 — not just the new review button. The
# migration file was in the repo and every gate was green; nothing had ever run
# `migrate` against production, because that step lived only in someone's head.
#
# Both databases are migrated, always. They are two databases on one Postgres
# server (see CLAUDE.md), and a deploy that migrates only the first leaves the
# opt-in landing DB silently behind until something reads it.
#
# `set -e` is the point: a migration that cannot apply must fail the deploy
# rather than ship an app whose queries reference tables that do not exist.

set -e

cd "$(dirname "$0")/../backend"

python manage.py migrate --noinput
python manage.py migrate --database=landing --noinput
