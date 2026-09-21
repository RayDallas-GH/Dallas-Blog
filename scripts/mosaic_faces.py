#!/usr/bin/env python3
"""家族が写った写真にモザイクをかけてから記事に使うための雛形。

CLAUDE.md「撮影写真の採用・アップロード方針」の例外の例外（2026-09-22決定）に対応する。
原本はWordPressにアップロードせず、このスクリプトの出力だけをアップロードすること。

使い方（座標はプレビュー画像＝長辺900pxでの座標で指定する）:

    from mosaic_faces import mosaic
    mosaic("~/Downloads/IMG_9408.JPG", "lounge-hana-kids-1.jpg", [(116, 428, 358, 648)])

座標の出し方:
    sips -Z 900 ~/Downloads/IMG_9408.JPG --out prev.jpg
    # prev.jpg を目で見て、隠したい範囲の (x0, y0, x1, y1) を読む

注意:
    - 範囲は顔だけでなく全身。手足がはみ出しやすいので、出力を必ず目で確認する
    - 出力ファイル名は原本と区別できる名前にする（IMG_XXXX のままにしない）
"""
from pathlib import Path

from PIL import Image, ImageDraw


def mosaic(src, dst, boxes_prev, prev_long=900, out_long=1600, cell_ratio=0.018):
    """boxes_prev で指定した矩形をピクセル化して dst に書き出す。

    boxes_prev: [(x0, y0, x1, y1), ...] 長辺 prev_long px のプレビュー座標
    cell_ratio: モザイクの粗さ（画像長辺に対する1マスの比率）
    out_long:   出力画像の長辺px
    """
    im = Image.open(Path(src).expanduser()).convert("RGB")
    w, h = im.size
    scale = max(w, h) / prev_long
    cell = max(8, int(max(w, h) * cell_ratio))
    pixelated = im.resize((max(1, w // cell), max(1, h // cell)), Image.BILINEAR)
    pixelated = pixelated.resize((w, h), Image.NEAREST)

    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    for x0, y0, x1, y1 in boxes_prev:
        draw.rounded_rectangle(
            [x0 * scale, y0 * scale, x1 * scale, y1 * scale],
            radius=int(min(x1 - x0, y1 - y0) * scale * 0.25),
            fill=255,
        )

    im = Image.composite(pixelated, im, mask)
    ratio = out_long / max(w, h)
    im = im.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
    im.save(dst, quality=88, optimize=True)
    return dst
