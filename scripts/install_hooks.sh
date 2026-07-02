#!/bin/bash
# scripts/hooks/ 内のGitフックを .git/hooks/ にインストールする。
# .git/hooks/ はgit管理外なので、リポジトリを新しくcloneした環境では
# 最初に一度これを実行する必要がある。
set -e
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

for hook in scripts/hooks/*; do
    name="$(basename "$hook")"
    cp "$hook" ".git/hooks/$name"
    chmod +x ".git/hooks/$name"
    echo "installed: .git/hooks/$name"
done
