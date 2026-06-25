# ブログ運用自動化プロジェクト（ibis-dallas.com）

## 目標
Cursor起点でブログ記事を編集・管理し、WordPressへの手動コピペをなくす。

---

## 環境情報

| 項目 | 内容 |
|------|------|
| サーバー | エックスサーバー |
| SSHコマンド | `ssh -p 10022 -i ~/.ssh/tokitoki777.key tokitoki777@tokitoki777.xsrv.jp` |
| WPパス | `~/ibis-dallas.com/public_html` |
| DBName | `tokitoki777_wp1` |
| GitHub | https://github.com/RayDallas-GH/Dallas-Blog.git |
| WP-CLI | v2.8.1 |

---

## 現在のブログ執筆フロー（改善前）

1. Cursorで文章作成・修正
2. WordPressに手動コピペ
3. 画像をWPにアップロード → URLをコピー
4. CursorにURLを貼り付けて編集
5. またWPに手動コピペ
6. GitHubにコミット

**問題点：** 画像URL取得のためにWP↔Cursor間を2回往復。毎回手動コピペが発生。

---

## 目指すフロー

1. WPに画像をまとめてアップロード
2. `get_media.sh`で画像情報（URL・代替テキスト）をCSV取得
3. Cursorで記事作成（画像URLはCSVから参照、AIが配置）
4. `git push` → GitHub Actions → WPに自動反映

---

## 完了済み ✅

- エックスサーバーSSH接続（公開鍵認証）
  - 秘密鍵：`~/.ssh/tokitoki777.key`
  - 公開鍵はサーバーパネルに登録済み
- WP-CLI動作確認（v2.8.1）
- 画像情報取得スクリプト作成（`~/get_media.sh`）
  - 日付指定で画像ID・URL・代替テキストを取得
  - 使い方：`~/get_media.sh`（当日）または `~/get_media.sh 2026-06-16`（日付指定）

---

## 残タスク

### Step 1：画像情報の自動取得 ✅ 完了

- [x] `get_media.sh`をCSV出力形式に改良（ヘッダー付き、id/title/url/alt_text）
- [x] `~/.zshrc`にSSHショートカットを登録
  ```bash
  # SSH接続
  alias xsv='ssh -p 10022 -i ~/.ssh/tokitoki777.key tokitoki777@tokitoki777.xsrv.jp'
  # CSV取得 → Desktopに保存（引数なし=今日、引数あり=日付指定 例: get_media 20260616）
  get_media() { ... }  # ~/.zshrc参照
  ```
- [x] CSVをCursorに渡して記事に画像を配置するワークフロー確立

**ワークフロー：**
1. WPに画像をまとめてアップロード＋代替テキスト設定
2. ターミナルで `get_media 20260616`（日付8桁）→ `~/Desktop/media_YYYY-MM-DD.csv` に自動保存
3. CursorでCSVを参照しながら記事のMarkdownを作成（urlとalt_textをimg srcに使う）

### Step 2：GitHub Actions → WP自動デプロイ ✅ 完了

- [x] `<!-- wp_post_id: N -->` を95件のmdファイルに一括挿入
- [x] `.github/workflows/deploy.yml` 作成
- [x] GitHub Secrets登録（SSH_PRIVATE_KEY / SSH_HOST / SSH_PORT / SSH_USER）
- [x] エックスサーバーの「国外アクセス制限」をOFFに変更
- [x] 動作確認済み（ウェスティンホテル横浜 post 31868 updated）

**デプロイの仕組み：**
- `git push` → `.md`ファイルが変更されていた場合のみActionsが起動
- 変更ファイルの先頭から `wp_post_id` を読み取り
- SCP → SSH → `wp post update` で本文を自動更新
- 所要時間：約24秒

**新規記事の追加方法：**
1. `.md`ファイルを作成し、WPで先に記事を作成してIDを確認
2. ファイル先頭に `<!-- wp_post_id: N -->` を追記
3. `git push` で自動反映

### Step 3：代替テキストの半自動化
- [ ] ファイル名・ホテル名からAIが代替テキストを提案
- [ ] WPアップロード時に自動設定する仕組み

---

## メモ

- GitHubリポジトリはパブリック公開中（記事は全公開なので問題なし）
- 過去記事の一部のみGitHub管理（収益貢献・こだわり記事のみ）
- トマレバ→Hotelierの置き換えはSQL/PHPで本番DB直接実行済み
  → CursorのMarkdownファイルには未反映（Step 2完了後に同期される）
- ローカル環境（Local by Flywheel）はセットアップ未完了
  → Step 2の自動デプロイが完成すればLocal環境は不要になる可能性あり
