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
  - 「今回の宿泊データ」ボックスの有無（警告のみ。内容の真偽はlintで検証できないため存在チェックに留める。
    過去記事への遡及追加はしない方針＝新規記事のみ対象。CLAUDE.md参照）

新規追加ファイルのみ厳格チェック（スタイル系・2026-09-21追加）:
  - 各H2セクションの直下（H3が挟まる場合はH3直下）に画像があるか
  - 1段落＝1文になっているか（<p>内に句点が2つ以上ないか）
  - 同じ文末表現が3連続していないか（2連続まで）
  - 本文に絵文字が含まれていないか（WPがエンティティ化しデプロイ検証が落ちる）
  - ヒルトン記事の「本記事の信頼性」ボックスが General/本記事の信頼性.md の定型文と一致するか
  - 全角英数字の混入（警告のみ）

WP側の状態（アイキャッチ・カテゴリー・スラッグ・下書き時刻・画像のtitle/alt）は
このlintでは検査できない。scripts/check_wp_state.py で別途チェックする。
両方まとめて回すには scripts/finish_article.sh を使う。

エラー（exit 1）: 規約違反の可能性が高いもの
警告（exit 0だが表示）: 見落としがちだが誤検知もあり得るもの

使い方:
  lint_articles.py <changed_file1.md> [changed_file2.md ...] --new <new_file1.md> [...]
"""
from __future__ import annotations   # macOS標準のPython3.9でも動かすため

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INTERNAL_LINKS_FILE = REPO_ROOT / "内部リンクURL.md"
# check_wp_state.py がWP側で実在を確認した未公開スラッグ（相互リンクしあう下書き記事用）
PENDING_SLUGS_FILE = REPO_ROOT / "scripts" / "pending_slugs.txt"
# 「今は対応できないが忘れてはいけない」項目の繰延登録（例：公開後でないと張れない相互リンク）。
# 形式: ファイルパス<TAB>チェックID<TAB>理由。該当エラーは [繰延] 付きの警告に落とし、実行のたびに表示する。
DEFERRED_FILE = REPO_ROOT / "scripts" / "deferred_checks.tsv"
DEFERRABLE_CHECKS = {
    "summary_nlink": "一覧まとめ記事への[nlink]が見つかりません",
    "h2_image": "の直下に画像（wp:image / wp:gallery）がありません",
    "consecutive_images": "単体の画像ブロックが2枚連続しています",
    "one_sentence": "1段落に2文以上入っています",
    "sentence_endings": "連続しています（2連続まで）",
    "trust_box": "「本記事の信頼性」ボックス",
    "stay_data_box": "「今回の宿泊データ」ボックスが見つかりません",
}

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


def load_deferred(path: Path) -> list[tuple[str, str]]:
    """このファイルに登録された繰延項目 [(チェックID, 理由), ...] を返す。"""
    if not DEFERRED_FILE.exists():
        return []
    out = []
    for line in DEFERRED_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) >= 2 and cols[0].strip() == str(path):
            out.append((cols[1].strip(), cols[2].strip() if len(cols) > 2 else ""))
    return out


def apply_deferrals(path: Path, errors: list[str], warnings: list[str]) -> tuple[list[str], list[str]]:
    deferred = load_deferred(path)
    if not deferred:
        return errors, warnings
    remaining = []
    for e in errors:
        hit = next((d for d in deferred
                    if d[0] in DEFERRABLE_CHECKS and DEFERRABLE_CHECKS[d[0]] in e), None)
        if hit:
            warnings.append(f"[繰延] {e}（理由: {hit[1] or '未記入'} / {DEFERRED_FILE.name} に登録済み）")
        else:
            remaining.append(e)
    return remaining, warnings


def load_pending_slugs() -> set[str]:
    if not PENDING_SLUGS_FILE.exists():
        return set()
    return {l.strip() for l in PENDING_SLUGS_FILE.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")}


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


def check_common(path: Path, known_slugs: set[str], nlink_warn_only: bool = False) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    text = path.read_text(encoding="utf-8")

    if "wp_post_id:" not in text[:200]:
        warnings.append("wp_post_id コメントが見つかりません（自動デプロイでSKIPされます）")

    if "posted with トマレバ" in text or "tomareba.com" in text:
        errors.append("トマレバの残骸（'posted with トマレバ' または tomareba.com）が残っています")

    nlink_urls = re.findall(r'\[nlink url="https://ibis-dallas\.com/([a-z0-9\-]+)"\]', text)
    for slug in nlink_urls:
        if known_slugs and slug not in known_slugs and slug not in SUMMARY_URLS:
            if slug in load_pending_slugs():
                # WP側に下書きとして実在することを check_wp_state.py が確認済み
                warnings.append(f"[nlink] のリンク先 '{slug}' はまだ未公開です"
                                "（公開後に ./scripts/update_internal_links.sh を実行する）")
                continue
            msg = f"[nlink] のリンク先 '{slug}' が内部リンクURL.mdに見つかりません（未公開記事の可能性）"
            # finish_article.sh から呼ぶときは check_wp_state.py がWP側で実在確認するため警告に落とす
            (warnings if nlink_warn_only else errors).append(msg)

    ext_links = re.findall(r'<a\s+class="shiny-btn3"\s+href="(https?://[^"]+)"([^>]*)>', text)
    for url, attrs in ext_links:
        if "ibis-dallas.com" not in url and "rel=" not in attrs:
            errors.append(f"外部リンクに rel=\"nofollow\" がありません: {url}")

    for target in find_broken_anchors(text):
        warnings.append(f"アンカーリンク切れの可能性: href=\"#{target}\" に対応する id=\"{target}\" が見つかりません")

    return errors, warnings


def check_stay_data_box(text: str) -> list[str]:
    """今回の宿泊データボックスの存在確認（新規記事のみ・warningのみ）。
    内容が事実かどうかはlintで検証できないため、存在チェックに留める。
    過去記事への遡及追加はしない方針（CLAUDE.md参照）なので新規記事にのみ適用する。"""
    if not re.search(r'\[box class="glay_box" title="今回の宿泊データ"\]', text):
        return ["「今回の宿泊データ」ボックスが見つかりません（新規記事では推奨。実体験でなく参考情報の記事なら不要）"]
    return []


def check_new_hotel_review(path: Path, text: str) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
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

    warnings.extend(check_stay_data_box(text))

    return errors, warnings


def check_new_overseas_hotel_review(text: str) -> tuple[list[str], list[str]]:
    errors, warnings = [], []

    if not has_h2_heading(text, "anker6", "朝食"):
        errors.append("朝食セクションが見つかりません（H2見出しで「朝食」を含む独立セクションが必須）")

    yadokko_count = len(re.findall(r'\[yadokko id="\d+"\]', text))
    if yadokko_count < 3:
        errors.append(f"Yadokkoカードが{yadokko_count}枚しかありません（海外ホテル宿泊記は最低3枚必要）")

    if not re.search(r'<h2[^>]*id="anker-card"', text):
        errors.append("クレカ訴求H2に id=\"anker-card\" が見つかりません（連番アンカーだと目次リンク切れの原因になる）")
    elif not re.search(r'href="#anker-card"', text):
        errors.append("目次に クレカ訴求セクション（#anker-card）へのリンクが見つかりません")

    warnings.extend(check_stay_data_box(text))

    return errors, warnings


# ---------------------------------------------------------------------------
# スタイル系チェック（2026-09-21追加）
# CLAUDE.mdに文章で書いてあるだけで機械チェックが無く、繰り返し違反していた項目を検査化したもの。
# 既存記事にはバックログが大量にあるため、新規追加ファイルのみ対象にする。
# ---------------------------------------------------------------------------

TRUST_BOX_FILE = REPO_ROOT / "ヒルトン" / "General" / "本記事の信頼性.md"

# WordPressが保存時にHTMLエンティティへ変換してしまう文字。
# デプロイの読み戻し検証がMISMATCHになるため本文に入れない（CLAUDE.md「記事本文に絵文字を書かない」）。
EMOJI_NON_BMP_RE = re.compile("[\U0001F000-\U0001FAFF\U0001F900-\U0001F9FF️]")
# BMP内の装飾記号。✓✔✕✗（チェック・バツ記号）は一覧表で使うため除外する。
EMOJI_BMP_RE = re.compile("[☀-✒✘-➿⬀-⯿]")

SENTENCE_ENDINGS = (
    "ませんでした", "ましょう", "でしょう", "ください",
    "でした", "ました", "ません", "です", "ます",
)


def strip_boilerplate_sections(text: str) -> str:
    """クレカ訴求セクション（id="anker-card"）を除いた本文を返す。
    このセクションは General/ の定型文をそのまま貼る運用なので、文体系のチェック対象から外す。"""
    m = re.search(r'<h2[^>]*id="anker-card"', text)
    if not m:
        return text
    rest = text[m.end():]
    nxt = re.search(r"<h2[^>]*>", rest)
    end = m.end() + nxt.start() if nxt else len(text)
    return text[:m.start()] + text[end:]


def _iter_paragraphs(text: str):
    """本文段落（<p>〜</p>）のプレーンテキストを返す。ショートコード行・空段落は除く。"""
    for m in re.finditer(r"<p>(.*?)</p>", text, re.DOTALL):
        plain = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        if not plain or plain.startswith("[") or plain.startswith("&nbsp;"):
            continue
        yield plain


def check_one_sentence_per_paragraph(text: str) -> list[str]:
    """1段落＝1文（句点ごとに改行）。CLAUDE.md「段落の書き方」。"""
    errors = []
    for plain in _iter_paragraphs(text):
        if plain.count("。") >= 2:
            errors.append(f"1段落に2文以上入っています（句点ごとに段落を分ける）: 「{plain[:45]}…」")
    return errors


def _ending_of(sentence: str) -> str | None:
    s = sentence.strip()
    for e in SENTENCE_ENDINGS:
        if s.endswith(e):
            return e
    return None


def check_repeated_sentence_endings(text: str, limit: int = 3) -> list[str]:
    """同じ語尾を3連続させない（2連続まで）。CLAUDE.md「文末ルール」。"""
    sentences = []
    for plain in _iter_paragraphs(text):
        sentences.extend(s.strip() for s in plain.split("。") if s.strip())

    runs, prev, count, start = [], None, 0, 0
    for i, s in enumerate(sentences):
        e = _ending_of(s)
        if e is not None and e == prev:
            count += 1
            continue
        if prev is not None and count >= limit:
            runs.append((prev, count, start))
        prev, count, start = e, (1 if e else 0), i
    if prev is not None and count >= limit:
        runs.append((prev, count, start))

    errors = []
    for ending, count, idx in runs:
        excerpt = " / ".join(f"…{s[-14:]}。" for s in sentences[idx:idx + count][:3])
        errors.append(f"文末「{ending}。」が{count}連続しています（2連続まで）: {excerpt}")
    return errors


def check_h2_lead_image(text: str) -> list[str]:
    """各H2セクションの直下（H3が挟まる場合はH3直下）に画像があるか。CLAUDE.md「セクション内の画像配置ルール」。"""
    errors = []
    h2s = list(re.finditer(r"<h2[^>]*>(.*?)</h2>", text, re.DOTALL))
    for i, m in enumerate(h2s):
        # クレカ訴求セクションは General/ の定型文をそのまま貼る運用のため対象外
        # （マリオット版の定型文はH2直下が本文から始まる）
        if 'id="anker-card"' in m.group(0):
            continue
        end = h2s[i + 1].start() if i + 1 < len(h2s) else len(text)
        section = text[m.end():end]
        first, skipped_heading = None, False
        for block in re.findall(r"<!-- wp:(\w+)", section):
            if block == "heading" and not skipped_heading:
                skipped_heading = True   # H3を1つだけ読み飛ばす
                continue
            first = block
            break
        if first not in ("image", "gallery"):
            title = re.sub(r"<[^>]+>", "", m.group(1)).strip()[:32]
            errors.append(f"H2「{title}」の直下に画像（wp:image / wp:gallery）がありません")
    return errors


def check_consecutive_images(text: str) -> list[str]:
    """単体の画像ブロックが2枚以上連続していないか。
    CLAUDE.mdの画像配置ルールは「H2直下に1枚 + 残りは該当する説明文の直後にギャラリーで分散」。
    単体画像を並べると、H2直下が2枚になったり別セクションの写真が紛れたりする
    （2026-09-21に実際に発生：施設・客室の写真が会員特典/クラブラウンジのH2直下に入った）。"""
    stripped = re.sub(r"<!-- wp:gallery.*?<!-- /wp:gallery -->", "<!-- wp:GALLERY -->", text, flags=re.DOTALL)
    positions = [(m.start(), m.group(1)) for m in re.finditer(r"<!-- wp:(\w+)", stripped)]
    errors = []
    for i in range(len(positions) - 1):
        if positions[i][1] == "image" and positions[i + 1][1] == "image":
            seg = stripped[positions[i][0]: positions[i + 1][0] + 400]
            alts = re.findall(r'alt="([^"]*)"', seg)[:2]
            errors.append("単体の画像ブロックが2枚連続しています"
                          "（H2直下は1枚。複数並べるならギャラリーにする）: "
                          + " / ".join(a[:30] for a in alts))
    return errors


def check_emoji(text: str) -> list[str]:
    """本文の絵文字。WPがエンティティ化してデプロイ読み戻し検証が落ちる。"""
    found = sorted(set(EMOJI_NON_BMP_RE.findall(text)))
    if found:
        return [f"本文に絵文字が含まれています（デプロイ検証がMISMATCHで落ちます）: {' '.join(found)}"]
    return []


def check_emoji_bmp(text: str) -> list[str]:
    found = sorted(set(EMOJI_BMP_RE.findall(text)))
    if found:
        return [f"装飾記号がWP側でエンティティ化される可能性があります（定型文からのコピー時は落とす）: {' '.join(found)}"]
    return []


def check_fullwidth_alnum(text: str) -> list[str]:
    """全角英数字の混入（2026-07-17に全記事を半角統一済み）。"""
    found = sorted(set(re.findall(r"[０-９Ａ-Ｚａ-ｚ]", text)))
    if found:
        return [f"全角英数字が混入しています（半角に統一）: {' '.join(found[:10])}"]
    return []


def _trust_box_items(text: str) -> list[str] | None:
    m = re.search(r'\[box class="yellow_box" title="本記事の信頼性"\](.*?)\[/box\]', text, re.DOTALL)
    if not m:
        return None
    return [re.sub(r"<[^>]+>", "", li).strip() for li in re.findall(r"<li>(.*?)</li>", m.group(1), re.DOTALL)]


def check_trust_box(text: str) -> list[str]:
    """ヒルトン記事の「本記事の信頼性」ボックスが General/本記事の信頼性.md の定型文と一致するか。
    定型文があるのに内容を書き換えて使った違反（2026-09-21 ヒルトン長崎）を検知する。"""
    if not TRUST_BOX_FILE.exists():
        return []
    template_items = _trust_box_items(TRUST_BOX_FILE.read_text(encoding="utf-8")) or []
    items = _trust_box_items(text)
    if items is None:
        return ['「本記事の信頼性」ボックス（yellow_box）がありません（ヒルトン記事では必須。'
                f'定型文: {TRUST_BOX_FILE.relative_to(REPO_ROOT)}）']
    if items != template_items:
        diff = [x for x in items if x not in template_items]
        msg = ('「本記事の信頼性」ボックスが定型文と一致しません'
               f'（定型文: {TRUST_BOX_FILE.relative_to(REPO_ROOT)} をそのまま使う）')
        if diff:
            msg += f" / 定型文に無い項目: {' 、'.join(d[:30] for d in diff[:3])}"
        return [msg]
    return []


def check_style(path: Path, text: str) -> tuple[list[str], list[str]]:
    """新規記事に適用するスタイル系チェックをまとめて実行する。"""
    if "テンプレート" in path.parts or "General" in path.parts:
        return [], []

    errors: list[str] = []
    warnings: list[str] = []
    body = strip_boilerplate_sections(text)   # 定型文セクションは文体チェックの対象外
    errors.extend(check_h2_lead_image(text))
    errors.extend(check_consecutive_images(text))
    errors.extend(check_one_sentence_per_paragraph(body))
    errors.extend(check_repeated_sentence_endings(body))
    errors.extend(check_emoji(text))
    warnings.extend(check_emoji_bmp(text))
    warnings.extend(check_fullwidth_alnum(text))
    if "ヒルトン" in path.parts:
        errors.extend(check_trust_box(text))
    return errors, warnings


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


def main(changed_files: list[str], new_files: list[str], nlink_warn_only: bool = False) -> int:
    known_slugs = load_known_slugs()
    had_error = False
    new_set = set(new_files)

    for f in changed_files:
        path = Path(f)
        if not path.exists() or path.suffix != ".md" or path.name in SKIP_NAMES:
            continue

        errors, warnings = check_common(path, known_slugs, nlink_warn_only)

        if f in new_set and f not in LEGACY_IMPORT_PATHS:
            style_errors, style_warnings = check_style(path, path.read_text(encoding="utf-8"))
            errors.extend(style_errors)
            warnings.extend(style_warnings)

        if f in new_set and is_domestic_hotel_review(path) and f not in LEGACY_IMPORT_PATHS:
            new_errors, new_warnings = check_new_hotel_review(path, path.read_text(encoding="utf-8"))
            errors.extend(new_errors)
            warnings.extend(new_warnings)
        elif f in new_set and is_overseas_hotel_review(path) and f not in LEGACY_IMPORT_PATHS:
            new_errors, new_warnings = check_new_overseas_hotel_review(path.read_text(encoding="utf-8"))
            errors.extend(new_errors)
            warnings.extend(new_warnings)

        errors, warnings = apply_deferrals(path, errors, warnings)
        errors = list(dict.fromkeys(errors))
        warnings = list(dict.fromkeys(warnings))

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
    nlink_warn_only = "--nlink-warn-only" in args
    args = [a for a in args if a != "--nlink-warn-only"]
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

    sys.exit(main(changed, new, nlink_warn_only))
