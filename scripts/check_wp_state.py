#!/usr/bin/env python3
"""
WordPress側の状態をチェックする（lint_articles.py では見られない項目）。

mdファイルだけを見ても分からない「記事の体裁を整える後工程」が毎回抜け落ちるため、
wp-cli経由で実際のWPの状態を機械的に確認する。

チェック項目（エラー = 未対応・修正が必要）:
  - 投稿が存在するか（wp_post_id が正しいか）
  - アイキャッチ画像（_thumbnail_id）が設定されているか
  - カテゴリーが設定されているか（未分類のままでないか）
  - スラッグ（post_name）が半角英数ハイフンか（日本語タイトルの自動生成のままでないか）
  - 下書き・予約投稿の post_date が 19:00（JST）／post_date_gmt が 10:00 か
  - 本文中の全画像の title・alt が設定されているか（IMG_1234 等のファイル名のままでないか）

  - [nlink] のリンク先スラッグがWPに実在するか（下書きなら警告）

警告（表示のみ）:
  - 画像の title と alt の文言が違う（CLAUDE.md は同一文言を推奨）
  - ローカルの .md と WP本文が一致しない（デプロイ未反映 or 絵文字のエンティティ化）
  - wp_title と WP側の post_title が一致しない

使い方:
  check_wp_state.py <file1.md> [file2.md ...]
"""
import html
import json
import re
import subprocess
import sys
from pathlib import Path

SSH = [
    "ssh", "-o", "ConnectTimeout=20", "-p", "10022",
    "-i", str(Path.home() / ".ssh" / "tokitoki777.key"),
    "tokitoki777@tokitoki777.xsrv.jp",
]
WP = "wp --path=/home/tokitoki777/ibis-dallas.com/public_html eval-file - 2>&1"

DRAFT_STATUSES = {"draft", "pending", "future", "auto-draft"}
# WP側で実在を確認できた未公開スラッグのキャッシュ。
# pre-pushフック（lint_articles.py）は 内部リンクURL.md に無いスラッグをエラーにするが、
# 相互リンクしあう下書き記事はどちらも未公開でエラーになりpushできない。
# 「WPに下書きとして実在する」ことをここで確認したものだけを記録し、lint側は警告に落とす。
PENDING_SLUGS_FILE = Path(__file__).resolve().parent / "pending_slugs.txt"
UNCATEGORIZED = {"未分類", "Uncategorized"}
FILENAME_LIKE = re.compile(r"^(IMG[_-]?\d+|DSC[_-]?\d+|PXL[_-]?\d+|image\d*|photo\d*|スクリーンショット.*)$", re.IGNORECASE)

PHP_TEMPLATE = """<?php
$IN = json_decode(<<<'JSONDATA'
%s
JSONDATA
, true);
$pid = (int)$IN['post_id'];
$p = get_post($pid);
if (!$p) { echo json_encode(['post_exists' => false]); exit; }
$out = [
  'post_exists'   => true,
  'post_status'   => $p->post_status,
  'post_name'     => $p->post_name,
  'post_title'    => $p->post_title,
  'post_date'     => $p->post_date,
  'post_date_gmt' => $p->post_date_gmt,
  'post_type'     => $p->post_type,
  'thumbnail_id'  => get_post_meta($pid, '_thumbnail_id', true),
  'categories'    => wp_get_post_terms($pid, 'category', ['fields' => 'names']),
  'content'       => $p->post_content,
];
$tid = (int)$out['thumbnail_id'];
$out['thumbnail_ok'] = ($tid && get_post($tid)) ? true : false;
$media = [];
foreach ($IN['media_ids'] as $mid) {
  $m = get_post((int)$mid);
  $media[(string)$mid] = $m
    ? ['exists' => true, 'title' => $m->post_title, 'alt' => (string)get_post_meta((int)$mid, '_wp_attachment_image_alt', true)]
    : ['exists' => false];
}
$out['media'] = $media;
$slugs = [];
foreach ($IN['nlink_slugs'] as $slug) {
  // get_posts の 'any' は下書きを拾わないので、ステータスを明示する
  $q = get_posts(['name' => $slug, 'post_type' => 'post',
                  'post_status' => ['publish', 'draft', 'future', 'pending', 'private'], 'numberposts' => 1]);
  $slugs[$slug] = $q ? $q[0]->post_status : false;
}
$out['nlink_slugs'] = $slugs;
echo json_encode($out, JSON_UNESCAPED_UNICODE);
"""


def parse_md(path: Path) -> tuple[int | None, str | None, str]:
    text = path.read_text(encoding="utf-8")
    pid = re.search(r"<!--\s*wp_post_id:\s*(\d+)\s*-->", text[:400])
    title = re.search(r"<!--\s*wp_title:\s*(.*?)\s*-->", text[:1000])
    body = re.sub(r"^<!--\s*wp_(post_id|title):.*?-->\n", "", text, count=2, flags=re.MULTILINE)
    return (int(pid.group(1)) if pid else None,
            title.group(1) if title else None,
            body)


def media_ids(body: str) -> list[int]:
    ids: list[int] = []
    for m in re.finditer(r'<!-- wp:image \{"id":(\d+)', body):
        ids.append(int(m.group(1)))
    for m in re.finditer(r'class="wp-image-(\d+)"', body):
        ids.append(int(m.group(1)))
    for m in re.finditer(r'\[gallery[^\]]*ids="([\d,\s]+)"', body):
        ids.extend(int(x) for x in re.findall(r"\d+", m.group(1)))
    return sorted(set(ids))


def nlink_slugs(body: str) -> list[str]:
    return sorted(set(re.findall(r'\[nlink url="https://ibis-dallas\.com/([a-z0-9\-]+)"', body)))


def fetch_state(post_id: int, mids: list[int], slugs: list[str] | None = None) -> dict:
    payload = json.dumps({"post_id": post_id, "media_ids": mids, "nlink_slugs": slugs or []}, ensure_ascii=False)
    php = PHP_TEMPLATE % payload
    proc = subprocess.run(SSH + [WP], input=php, capture_output=True, text=True)
    raw = proc.stdout.strip()
    start = raw.find("{")
    if start == -1:
        raise RuntimeError(f"WPからの応答を解析できません: {raw[:300] or proc.stderr[:300]}")
    return json.loads(raw[start:])


def normalize(text: str) -> str:
    text = html.unescape(text).replace("\r\n", "\n")
    return "\n".join(line.rstrip() for line in text.strip().split("\n"))


def update_pending_slugs(slug_status: dict) -> None:
    """未公開スラッグのキャッシュを更新する（公開済みになったスラッグは削除）。"""
    if not slug_status:
        return
    current = set()
    if PENDING_SLUGS_FILE.exists():
        current = {l.strip() for l in PENDING_SLUGS_FILE.read_text(encoding="utf-8").splitlines()
                   if l.strip() and not l.startswith("#")}
    for slug, st in slug_status.items():
        if st and st != "publish":
            current.add(slug)
        else:
            current.discard(slug)
    header = ("# WPに下書き（未公開）として実在することを check_wp_state.py が確認したスラッグ。\n"
              "# lint_articles.py はこれらを「未公開だが実在する」として警告扱いにする。\n"
              "# 公開されると自動で削除される。手で編集しない。\n")
    PENDING_SLUGS_FILE.write_text(header + "\n".join(sorted(current)) + "\n", encoding="utf-8")


def check_file(path: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    post_id, wp_title, body = parse_md(path)
    if post_id is None:
        return ["wp_post_id コメントがありません（WPに反映されません）"], []

    state = fetch_state(post_id, media_ids(body), nlink_slugs(body))
    if not state.get("post_exists"):
        return [f"WPに post_id {post_id} の投稿が見つかりません"], []

    status = state["post_status"]

    if not state["thumbnail_ok"]:
        errors.append(f"アイキャッチ画像が未設定です → wp post meta update {post_id} _thumbnail_id MEDIA_ID")

    cats = [c for c in state["categories"] if c not in UNCATEGORIZED]
    if not cats:
        errors.append(f"カテゴリーが未設定（または未分類のまま）です → wp post update {post_id} --post_category=TERM_ID")

    slug = state["post_name"]
    if not slug:
        errors.append(f"スラッグ（post_name）が空です → wp post update {post_id} --post_name=スラッグ")
    elif not re.fullmatch(r"[a-z0-9\-]+", slug):
        errors.append(f"スラッグが半角英数ハイフンになっていません（自動生成のままの可能性）: '{slug[:40]}'")

    if status in DRAFT_STATUSES:
        date, date_gmt = state["post_date"], state["post_date_gmt"]
        if not date.endswith(" 19:00:00"):
            errors.append(f"下書きの post_date が19:00（JST）ではありません: {date} "
                          f'→ wp post update {post_id} --post_date="YYYY-MM-DD 19:00:00" --post_date_gmt="YYYY-MM-DD 10:00:00"')
        elif not date_gmt.endswith(" 10:00:00"):
            errors.append(f"post_date は19:00ですが post_date_gmt が10:00ではありません: {date_gmt}（JST-9で手計算して渡す）")

    for mid, info in sorted(state["media"].items(), key=lambda kv: int(kv[0])):
        if not info.get("exists"):
            errors.append(f"本文が参照する画像 ID {mid} がWPに存在しません")
            continue
        title, alt = (info.get("title") or "").strip(), (info.get("alt") or "").strip()
        if not alt:
            errors.append(f"画像 ID {mid} の alt が未設定です")
        if not title or FILENAME_LIKE.match(title):
            errors.append(f"画像 ID {mid} の title がファイル名のままです: '{title}' → altと同じ説明文にする")
        elif alt and title != alt:
            warnings.append(f"画像 ID {mid} の title と alt の文言が違います（title='{title[:28]}' / alt='{alt[:28]}'）")

    update_pending_slugs(state.get("nlink_slugs", {}))
    for link_slug, st in sorted(state.get("nlink_slugs", {}).items()):
        if st is False:
            errors.append(f"[nlink] のリンク先 '{link_slug}' がWPに存在しません（スラッグの打ち間違い）")
        elif st != "publish":
            warnings.append(f"[nlink] のリンク先 '{link_slug}' はまだ公開されていません（{st}）。"
                            "公開後に ./scripts/update_internal_links.sh を実行して 内部リンクURL.md を更新する")

    if wp_title and wp_title != state["post_title"]:
        warnings.append(f"wp_title とWP側のタイトルが違います（WP側: '{state['post_title'][:40]}'）")

    if normalize(body) != normalize(state["content"]):
        warnings.append("ローカルの .md とWP本文が一致しません（デプロイ未反映の可能性。"
                        "gh run list で失敗が無いか確認し、必要なら再実行する）")

    print(f"  （参考）post_status={status} / slug={slug or '未設定'} / "
          f"post_date={state['post_date']} / カテゴリー={'、'.join(cats) or 'なし'} / 画像{len(state['media'])}枚")
    return errors, warnings


def main(paths: list[str]) -> int:
    had_error = False
    for f in paths:
        path = Path(f)
        print(f"\n■ {path}")
        if not path.exists():
            print("  [ERROR] ファイルが見つかりません")
            had_error = True
            continue
        try:
            errors, warnings = check_file(path)
        except Exception as e:   # SSH失敗・JSON解析失敗など
            print(f"  [ERROR] WP状態の取得に失敗しました: {e}")
            had_error = True
            continue
        for e in errors:
            print(f"  [ERROR] {e}")
            had_error = True
        for w in warnings:
            print(f"  [WARN]  {w}")
        if not errors and not warnings:
            print("  OK")
    return 1 if had_error else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("使い方: check_wp_state.py <file1.md> [file2.md ...]")
        sys.exit(0)
    sys.exit(main(args))
