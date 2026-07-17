#!/usr/bin/env python3
"""
記事mdファイルをCLAUDE.mdの規約に沿ってチェックする。
git push前のpre-pushフックから呼ばれる想定。

全ファイル共通チェック（既存記事の軽微な編集でも必ず通る軽さ）:
  - wp_post_id コメントの有無（無いと自動デプロイでSKIPされる → 警告のみ）
  - [nlink url="..."] のURLが 内部リンクURL.md に存在するか
  - トマレバの残骸（"posted with トマレバ" / tomareba.com）
  - shiny-btn3 の外部リンクに rel="nofollow" が無い

全ファイル共通チェック（追加分）:
  - 目次・本文中の `href="#ankerXXX"` が、本文中の `id="ankerXXX"` 見出しに対応しているか
    （壊れたアンカーリンクの検出。セクション増減でanker番号がズレて発生しやすい）

新規追加ファイルのみ厳格チェック（既存記事の編集ではスキップ。
過去記事に規約未整備のバックログが多いため、新規作成時のみ強制する）:
  - 国内ヒルトン/マリオット宿泊記で、まとめ記事へのnlinkが最低1つあるか
  - 国内ヒルトン/マリオット宿泊記で、朝食のH2見出し（id="anker5"またはH2テキストに「朝食」）があるか
  - 国内ヒルトン/マリオット宿泊記で、Yadokkoカードが最低2枚あるか
  - 国内ヒルトン/マリオット宿泊記で、クレカ訴求H2に`id="anker-card"`があり、目次からリンクされているか
  - 海外ヒルトン/マリオット宿泊記で、朝食のH2見出し（id="anker6"またはH2テキストに「朝食」）があるか
  - 海外ヒルトン/マリオット宿泊記で、Yadokkoカードが最低3枚あるか
  - 海外ヒルトン/マリオット宿泊記で、クレカ訴求H2に`id="anker-card"`があり、目次からリンクされているか

エラー（exit 1）: 規約違反の可能性が高いもの
警告（exit 0だが表示）: 見落としがちだが誤検知もあり得るもの

使い方:
  lint_articles.py <changed_file1.md> [changed_file2.md ...] --new <new_file1.md> [...]
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INTERNAL_LINKS_FILE = REPO_ROOT / "内部リンクURL.md"

SUMMARY_URLS = {
    "hilton-hotel-japan",
    "marriott-hotel-japan",
    "fairfield-hotel-japan",
}

HOTEL_CHAIN_DIRS = {"ヒルトン", "マリオット"}


def load_known_slugs() -> set[str]:
    if not INTERNAL_LINKS_FILE.exists():
        return set()
    text = INTERNAL_LINKS_FILE.read_text(encoding="utf-8")
    slugs = set()
    for m in re.finditer(r"https://ibis-dallas\.com/([a-z0-9\-]+)", text):
        slugs.add(m.group(1))
    return slugs


def is_domestic_hotel_review(path: Path) -> bool:
    parts = path.parts
    return any(p in HOTEL_CHAIN_DIRS for p in parts) and "国内ホテル" in parts


def is_overseas_hotel_review(path: Path) -> bool:
    parts = path.parts
    return any(p in HOTEL_CHAIN_DIRS for p in parts) and "海外ホテル" in parts


def find_broken_anchors(text: str) -> list[str]:
    """href="#ankerXXX" が本文中の id="ankerXXX" 見出しに対応しているか確認する。"""
    href_targets = set(re.findall(r'href="#(anker[\w-]+)"', text))
    ids_present = set(re.findall(r'id="(anker[\w-]+)"', text))
    return sorted(href_targets - ids_present)


def has_h2_heading(text: str, anchor_id: str, keyword: str) -> bool:
    """id属性一致、またはH2見出しテキストにkeywordを含むかで判定する（本文中の単語出現だけでは判定しない）。"""
    if re.search(rf'<h2[^>]*id="{anchor_id}"', text):
        return True
    for m in re.finditer(r"<h2[^>]*>(.*?)</h2>", text, re.DOTALL):
        if keyword in re.sub(r"<[^>]+>", "", m.group(1)):
            return True
    return False


def check_common(path: Path, known_slugs: set[str]) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    text = path.read_text(encoding="utf-8")

    if "wp_post_id:" not in text[:200]:
        warnings.append("wp_post_id コメントが見つかりません（自動デプロイでSKIPされます）")

    if "posted with トマレバ" in text or "tomareba.com" in text:
        errors.append("トマレバの残骸（'posted with トマレバ' または tomareba.com）が残っています")

    nlink_urls = re.findall(r'\[nlink url="https://ibis-dallas\.com/([a-z0-9\-]+)"\]', text)
    for slug in nlink_urls:
        if known_slugs and slug not in known_slugs and slug not in SUMMARY_URLS:
            errors.append(f"[nlink] のリンク先 '{slug}' が内部リンクURL.mdに見つかりません（未公開記事の可能性）")

    ext_links = re.findall(r'<a\s+class="shiny-btn3"\s+href="(https?://[^"]+)"([^>]*)>', text)
    for url, attrs in ext_links:
        if "ibis-dallas.com" not in url and "rel=" not in attrs:
            errors.append(f"外部リンクに rel=\"nofollow\" がありません: {url}")

    for target in find_broken_anchors(text):
        warnings.append(f"アンカーリンク切れの可能性: href=\"#{target}\" に対応する id=\"{target}\" が見つかりません")

    return errors, warnings


def check_new_hotel_review(path: Path, text: str) -> list[str]:
    errors = []
    nlink_urls = re.findall(r'\[nlink url="https://ibis-dallas\.com/([a-z0-9\-]+)"\]', text)

    if not any(slug in nlink_urls for slug in SUMMARY_URLS):
        errors.append("国内ホテル宿泊記なのに、一覧まとめ記事への[nlink]が見つかりません")

    if not has_h2_heading(text, "anker5", "朝食"):
        errors.append("朝食セクションが見つかりません（H2見出しで「朝食」を含む独立セクションが必須）")

    yadokko_count = len(re.findall(r'\[(?:hotelier|yadokko) id="\d+"\]', text))
    if yadokko_count < 2:
        errors.append(f"Yadokkoカードが{yadokko_count}枚しかありません（最低2枚必要）")

    if not re.search(r'<h2[^>]*id="anker-card"', text):
        errors.append("クレカ訴求H2に id=\"anker-card\" が見つかりません（連番アンカーだと目次リンク切れの原因になる）")
    elif not re.search(r'href="#anker-card"', text):
        errors.append("目次に クレカ訴求セクション（#anker-card）へのリンクが見つかりません")

    return errors


def check_new_overseas_hotel_review(text: str) -> list[str]:
    errors = []

    if not has_h2_heading(text, "anker6", "朝食"):
        errors.append("朝食セクションが見つかりません（H2見出しで「朝食」を含む独立セクションが必須）")

    yadokko_count = len(re.findall(r'\[yadokko id="\d+"\]', text))
    if yadokko_count < 3:
        errors.append(f"Yadokkoカードが{yadokko_count}枚しかありません（海外ホテル宿泊記は最低3枚必要）")

    if not re.search(r'<h2[^>]*id="anker-card"', text):
        errors.append("クレカ訴求H2に id=\"anker-card\" が見つかりません（連番アンカーだと目次リンク切れの原因になる）")
    elif not re.search(r'href="#anker-card"', text):
        errors.append("目次に クレカ訴求セクション（#anker-card）へのリンクが見つかりません")

    return errors


SKIP_NAMES = {"CLAUDE.md", "内部リンクURL.md", "紹介リンク.md", "ブログ記事案.md", "AUTOMATION.md", "writing-rules.md"}

# 既に公開済みの記事をgit管理下に初めて追加しただけのファイル（新規執筆ではない）。
# 新規記事向けの厳格チェック（まとめ記事nlink・朝食H2・カード2枚）は免除する。
# 双方向nlinkのバックログ対応は別タスクとして着手する（CLAUDE.md参照）。
LEGACY_IMPORT_PATHS = {
    "ヒルトン/国内ホテル/テラスクラブアットブセナ.md",
    "ヒルトン/国内ホテル/テラスクラブアットブセナクラブラウンジ.md",
    "ヒルトン/国内ホテル/テラスクラブアットブセナ朝食ビュッフェ.md",
    "マリオット/国内ホテル/フォーポイントバイシェラトン名古屋（セントレア）.md",
}


def main(changed_files: list[str], new_files: list[str]) -> int:
    known_slugs = load_known_slugs()
    had_error = False
    new_set = set(new_files)

    for f in changed_files:
        path = Path(f)
        if not path.exists() or path.suffix != ".md" or path.name in SKIP_NAMES:
            continue

        errors, warnings = check_common(path, known_slugs)

        if f in new_set and is_domestic_hotel_review(path) and f not in LEGACY_IMPORT_PATHS:
            errors.extend(check_new_hotel_review(path, path.read_text(encoding="utf-8")))
        elif f in new_set and is_overseas_hotel_review(path) and f not in LEGACY_IMPORT_PATHS:
            errors.extend(check_new_overseas_hotel_review(path.read_text(encoding="utf-8")))

        if errors or warnings:
            print(f"\n■ {path}")
            for e in errors:
                print(f"  [ERROR] {e}")
                had_error = True
            for w in warnings:
                print(f"  [WARN]  {w}")

    return 1 if had_error else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--new" in args:
        idx = args.index("--new")
        changed = args[:idx]
        new = args[idx + 1:]
    else:
        changed = args
        new = []

    if not changed:
        print("使い方: lint_articles.py <changed_file1.md> [...] --new <new_file1.md> [...]")
        sys.exit(0)

    sys.exit(main(changed, new))
