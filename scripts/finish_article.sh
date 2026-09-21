#!/bin/bash
# 記事を「完成」と判断する前に必ず通すチェックゲート。
#
#   ./scripts/finish_article.sh <記事.md> [記事2.md ...]
#
# A層：lint_articles.py（ファイル内容のチェック。新規記事向けの厳格モードで実行）
# B層：check_wp_state.py（WP側の状態。アイキャッチ・カテゴリー・スラッグ・下書き時刻・画像title/alt）
#
# 全項目PASSになるまで「修正 → 再実行」を繰り返す。
# PASSの出力が出るまで記事は完成扱いにしない（完了報告にはこの出力を貼る）。
#
# オプション:
#   --skip-wp   B層（SSH経由のWP状態チェック）を飛ばす。ネットワークが無いときの応急用

set -u
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

SKIP_WP=0
FILES=()
for arg in "$@"; do
    case "$arg" in
        --skip-wp) SKIP_WP=1 ;;
        *) FILES+=("$arg") ;;
    esac
done

if [ "${#FILES[@]}" -eq 0 ]; then
    echo "使い方: ./scripts/finish_article.sh <記事.md> [記事2.md ...] [--skip-wp]"
    exit 2
fi

for f in "${FILES[@]}"; do
    if [ ! -f "$f" ]; then
        echo "ファイルが見つかりません: $f"
        exit 2
    fi
done

lint_status=0
wp_status=0

echo "=============================================="
echo " A層：記事ファイルのチェック（lint_articles.py）"
echo "=============================================="
python3 scripts/lint_articles.py "${FILES[@]}" --nlink-warn-only --new "${FILES[@]}" || lint_status=1
[ "$lint_status" -eq 0 ] && echo "  エラーなし"

if [ "$SKIP_WP" -eq 1 ]; then
    echo ""
    echo "=============================================="
    echo " B層：WP状態チェック → --skip-wp によりスキップ"
    echo "=============================================="
    wp_status=2
else
    echo ""
    echo "=============================================="
    echo " B層：WordPress側の状態（check_wp_state.py）"
    echo "=============================================="
    python3 scripts/check_wp_state.py "${FILES[@]}" || wp_status=1
fi

echo ""
echo "=============================================="
if [ "$lint_status" -eq 0 ] && [ "$wp_status" -eq 0 ]; then
    echo " 目視確認用：見出しごとの画像一覧"
    echo "   （写真がそのセクションの内容と合っているかは機械では判定できない）"
    python3 scripts/article_map.py "${FILES[@]}"
    echo ""
    echo "=============================================="
    echo " ✅ 全項目PASS（$(date '+%Y-%m-%d %H:%M')）"
    echo " 対象: ${FILES[*]}"
    echo "=============================================="
    exit 0
fi

if [ "$lint_status" -eq 0 ] && [ "$wp_status" -eq 2 ]; then
    echo " ⚠️ A層のみPASS。B層（WP状態）は未確認のため完成扱いにしない"
    echo "=============================================="
    exit 1
fi

echo " ❌ 未達項目あり。上の [ERROR] を全て直してから再実行する"
[ "$lint_status" -ne 0 ] && echo "    - A層（記事ファイル）にエラーあり"
[ "$wp_status" -ne 0 ] && echo "    - B層（WP状態）にエラーあり"
echo " エラーがゼロになるまで完了報告しない（[WARN] は内容を確認したうえで判断する）"
echo "=============================================="
exit 1
