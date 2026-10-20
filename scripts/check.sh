#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
while IFS= read -r file; do bash -n "$file"; done < <(find server scripts -type f -name '*.sh')
python3 -m compileall -q server scripts
python3 scripts/test_portable.py
python3 scripts/test_actions_install.py
python3 scripts/test_apple_theme.py
node scripts/test_apple_theme.cjs
node scripts/test_prefetch.cjs
node scripts/test_family_watch.cjs
(cd server/recommender && KINOPOISK_PROFILE_ID=1234567 python3 -m unittest discover -p 'test_*.py')
(cd server/recommender && for file in test_*.cjs; do node "$file"; done)
(cd server/poster-cache && python3 -m unittest test_server test_kinoafisha_posters && node test_plugin.cjs)
echo 'All checks passed'
