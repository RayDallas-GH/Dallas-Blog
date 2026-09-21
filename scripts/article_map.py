#!/usr/bin/env python3
"""記事のセクション構成と、そこに置かれた画像の一覧を出力する（目視確認用）。

「その写真がそのセクションの内容と合っているか」は機械では判定できない。
別セクションの写真が紛れ込む事故（2026-09-21に発生）を人の目で拾えるように、
チェックがPASSしたタイミングで見出しごとの画像を並べて表示する。

使い方: article_map.py <記事.md>
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def main(paths: list[str]) -> int:
    for f in paths:
        text = Path(f).read_text(encoding="utf-8")
        print(f"\n■ {Path(f).name}")
        marks = [(m.start(), m.group(1).upper(), re.sub(r"<[^>]+>", "", m.group(2)).strip())
                 for m in re.finditer(r"<(h[23])[^>]*>(.*?)</\1>", text, re.DOTALL)]
        for i, (pos, level, title) in enumerate(marks):
            end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
            alts = re.findall(r'alt="([^"]*)"', text[pos:end])
            indent = "  " if level == "H2" else "    "
            print(f"{indent}{level} {title}（画像{len(alts)}枚）")
            for a in alts:
                print(f"{indent}   - {a}")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("使い方: article_map.py <記事.md> [...]")
        sys.exit(0)
    sys.exit(main(args))
