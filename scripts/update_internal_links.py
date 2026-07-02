#!/usr/bin/env python3
"""
内部リンクURL.md のうち「カテゴリー別記事分類」以降の自動生成セクションを、
WordPress側の最新の公開記事・カテゴリー情報から再生成する。

前半（カテゴリーページ一覧・手動キュレーションされた個別記事URL）は変更しない。

使い方:
  ./scripts/update_internal_links.sh
"""
import csv
import subprocess
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET_FILE = REPO_ROOT / "内部リンクURL.md"
SPLIT_MARKER = "## カテゴリー別記事分類"

SSH_CMD = [
    "ssh", "-p", "10022", "-i", str(Path.home() / ".ssh/tokitoki777.key"),
    "tokitoki777@tokitoki777.xsrv.jp",
]
WP_DIR = "cd ~/ibis-dallas.com/public_html && "


def run_remote(wp_command: str) -> str:
    result = subprocess.run(
        SSH_CMD + [WP_DIR + wp_command],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def fetch_data():
    categories_csv = run_remote(
        "wp term list category --fields=term_id,name,slug,parent,count --format=csv"
    )
    post_categories_tsv = run_remote(
        "wp db query \"SELECT p.post_name, t.slug AS cat_slug FROM wp_posts p "
        "JOIN wp_term_relationships tr ON tr.object_id=p.ID "
        "JOIN wp_term_taxonomy tt ON tt.term_taxonomy_id=tr.term_taxonomy_id AND tt.taxonomy='category' "
        "JOIN wp_terms t ON t.term_id=tt.term_id "
        "WHERE p.post_status='publish' AND p.post_type='post' ORDER BY p.post_name\" --skip-column-names"
    )
    all_posts_csv = run_remote(
        "wp post list --post_status=publish --post_type=post --fields=post_name --format=csv"
    )
    return categories_csv, post_categories_tsv, all_posts_csv


def build_section(categories_csv: str, post_categories_tsv: str, all_posts_csv: str) -> str:
    cats = {}
    for row in csv.DictReader(categories_csv.splitlines()):
        cats[row["term_id"]] = {"slug": row["slug"], "parent": row["parent"]}

    def build_path(term_id):
        parts, cur, seen = [], term_id, set()
        while cur and cur != "0" and cur not in seen:
            seen.add(cur)
            c = cats.get(cur)
            if not c:
                break
            parts.append(c["slug"])
            cur = c["parent"]
        return "/".join(reversed(parts))

    slug_to_path = {c["slug"]: build_path(tid) for tid, c in cats.items()}

    buckets = defaultdict(set)
    for line in post_categories_tsv.splitlines():
        line = line.rstrip("\n")
        if not line:
            continue
        post_name, cat_slug = line.split("\t")
        path = slug_to_path.get(cat_slug)
        if path:
            buckets[path].add(post_name)

    all_slugs = sorted({row["post_name"] for row in csv.DictReader(all_posts_csv.splitlines())})

    lines = [f"{SPLIT_MARKER}（{len(all_slugs)}件・WordPressカテゴリー設定より取得）", ""]
    for path in sorted(buckets.keys()):
        slugs = sorted(buckets[path])
        lines.append(f"## {path} ({len(slugs)}件)")
        lines.extend(f"https://ibis-dallas.com/{s}" for s in slugs)
        lines.append("")

    lines.append(f"## 全記事URL一覧（{len(all_slugs)}件・WP-CLIより取得）")
    lines.append("")
    lines.append("※上記のカテゴリ別URLと重複する場合があります")
    lines.append("")
    lines.extend(f"https://ibis-dallas.com/{s}" for s in all_slugs)

    return "\n".join(lines) + "\n"


def main():
    original = TARGET_FILE.read_text(encoding="utf-8")
    marker_idx = original.index(SPLIT_MARKER)
    header = original[:marker_idx]

    categories_csv, post_categories_tsv, all_posts_csv = fetch_data()
    auto_section = build_section(categories_csv, post_categories_tsv, all_posts_csv)

    TARGET_FILE.write_text(header + auto_section, encoding="utf-8")
    post_count = auto_section.count("https://")
    print(f"更新完了: {TARGET_FILE.name}（掲載URL数 約{post_count}件）")


if __name__ == "__main__":
    main()
