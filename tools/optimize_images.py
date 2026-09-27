"""docs/images 의 큰 이미지를 WebP 로 줄인다. (GitHub 저장소·Pages 용량 절약)

- 임계값(기본 600KB) 이상인 PNG/JPG 만 대상. 작은 이미지는 손대지 않는다.
- 변환 후 content/posts/*.json 안의 참조(../images/<id>/NN.png -> NN.webp)를 함께 고친다.
- 원본은 삭제한다 (필요하면 티스토리에서 다시 가져올 수 있다).

사용:  python tools/optimize_images.py [--threshold-kb 600] [--quality 85] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "docs" / "images"
POSTS = ROOT / "content" / "posts"
MAX_SIDE = 2000  # 이보다 큰 변은 줄인다 (본문 폭은 ~800px 이라 충분)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold-kb", type=int, default=600)
    ap.add_argument("--quality", type=int, default=85)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    before = after = 0
    renames: dict[str, list[tuple[str, str]]] = {}
    for f in sorted(IMAGES.rglob("*")):
        if f.suffix.lower() not in (".png", ".jpg", ".jpeg") or f.stat().st_size < a.threshold_kb * 1024:
            continue
        size0 = f.stat().st_size
        try:
            im = Image.open(f)
            im.load()
        except Exception as e:  # 깨진 파일은 건너뛴다
            print("skip", f, e)
            continue
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if "A" in im.getbands() or im.mode == "P" else "RGB")
        if max(im.size) > MAX_SIDE:
            im.thumbnail((MAX_SIDE, MAX_SIDE))
        out = f.with_suffix(".webp")
        if not a.dry_run:
            im.save(out, "WEBP", quality=a.quality, method=6)
            size1 = out.stat().st_size
            if size1 >= size0:  # 오히려 커지면 원본 유지
                out.unlink()
                continue
            f.unlink()
        else:
            size1 = size0 // 5
        before += size0
        after += size1
        renames.setdefault(f.parent.name, []).append((f.name, out.name))
        print(f"{f.parent.name}/{f.name}: {size0 / 1e6:.1f}MB -> {size1 / 1e6:.2f}MB")

    if not a.dry_run:
        for pid, pairs in renames.items():
            jf = POSTS / f"{pid}.json"
            if not jf.exists():
                continue
            p = json.loads(jf.read_text(encoding="utf-8"))
            for old, new in pairs:
                p["html"] = p["html"].replace(f"../images/{pid}/{old}", f"../images/{pid}/{new}")
            jf.write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"total: {before / 1e6:.0f}MB -> {after / 1e6:.0f}MB  ({len(renames)} posts)")


if __name__ == "__main__":
    main()
