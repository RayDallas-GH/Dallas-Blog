#!/bin/bash
# 内部リンクURL.md の自動生成セクションをWordPress最新データで更新する
set -e
cd "$(dirname "$0")/.."
python3 scripts/update_internal_links.py
