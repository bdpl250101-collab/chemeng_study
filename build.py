"""content/ -> docs/ 정적 사이트 빌드.

글 소스는 두 가지를 섞어 쓸 수 있다.
  content/posts/<id>.json   티스토리에서 가져온 글 (tools/import_tistory.py 가 만든다)
  content/posts/*.md        새로 쓰는 글. 맨 위에 front matter:
                            ---
                            title: 제목
                            date: 2026-10-01
                            category: 분리공정
                            tags: [증류, McCabe-Thiele]
                            ---
                            본문 (Markdown, 수식은 $...$ / $$...$$)

출력:
  docs/index.html                 홈 (과목 카드 + 최근 글)
  docs/category/<slug>.html       과목별 글 목록
  docs/posts/<id>.html            글 본문
  docs/images/...                 content/images 복사
  docs/search.json                검색 색인
  docs/assets/style.css, app.js

CLI:
    python build.py            # 전체 빌드
    python build.py --serve    # 빌드 후 http://localhost:8000 미리보기
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import zlib
from collections import defaultdict
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / "content"
POSTS_DIR = CONTENT / "posts"
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"
OUT = ROOT / "docs"

SITE = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))

# 티스토리 카테고리 이름의 표기 차이(대소문자, 번호 접미사)를 하나로 모은다
CATEGORY_ALIASES = {
    "lab & paper (1)": "Lab & paper",
    "lab & paper (2)": "Lab & paper",
    "lab & paper": "Lab & paper",
    "lab & paper (1)": "Lab & paper",
    "영어": "영어일지",
}


# ---------------------------------------------------------------------------
# 글 읽기
# ---------------------------------------------------------------------------
def normalize_category(raw: str) -> str:
    """'화학공학 일지/분리공정' -> '분리공정'. 상위 분류는 떼고 마지막 단계만 쓴다."""
    leaf = (raw or "").split("/")[-1].strip()
    leaf = CATEGORY_ALIASES.get(leaf.lower(), leaf)
    return leaf or "기타"


def strip_text(html_src: str, limit: int = 400) -> str:
    text = re.sub(r"<[^>]+>", " ", html_src)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def load_json_post(path: Path) -> dict:
    p = json.loads(path.read_text(encoding="utf-8"))
    p["category"] = normalize_category(p.get("category", ""))
    p["slug"] = str(p["id"])
    p["body"] = p.pop("html")
    p["excerpt"] = p.get("summary") or strip_text(p["body"], 200)
    p["text"] = strip_text(p["body"], 3000)
    p["origin"] = "tistory"
    return p


def parse_front_matter(src: str) -> tuple[dict, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", src, re.S)
    if not m:
        return {}, src
    meta: dict = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        v = v.strip()
        if v.startswith("[") and v.endswith("]"):
            meta[k.strip()] = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
        else:
            meta[k.strip()] = v.strip("'\"")
    return meta, m.group(2)


def load_md_post(path: Path) -> dict:
    import markdown  # 새 글을 쓸 때만 필요

    meta, body_md = parse_front_matter(path.read_text(encoding="utf-8"))
    # 수식 보호: Markdown 이 $...$ 안의 _ * 를 강조로 해석하지 않게 잠시 치환한다
    holders: list[str] = []

    def hold(m):
        holders.append(m.group(0))
        return f"\x00MATH{len(holders) - 1}\x00"

    protected = re.sub(r"\$\$.*?\$\$|\$[^$\n]+\$", hold, body_md, flags=re.S)
    body = markdown.markdown(protected, extensions=["tables", "fenced_code", "toc", "sane_lists"])
    body = re.sub(r"\x00MATH(\d+)\x00", lambda m: holders[int(m.group(1))], body)

    slug = meta.get("slug") or path.stem
    return {
        "id": slug,
        "slug": slug,
        "title": meta.get("title", path.stem),
        "date": meta.get("date", ""),
        "modified": meta.get("modified", meta.get("date", "")),
        "category": normalize_category(meta.get("category", "")),
        "tags": meta.get("tags", []) if isinstance(meta.get("tags"), list) else [],
        "summary": meta.get("summary", ""),
        "body": body,
        "excerpt": meta.get("summary") or strip_text(body, 200),
        "text": strip_text(body, 3000),
        "origin": "markdown",
        "source_url": "",
    }


def load_posts() -> list[dict]:
    posts = []
    for path in sorted(POSTS_DIR.glob("*.json")):
        posts.append(load_json_post(path))
    for path in sorted(POSTS_DIR.glob("*.md")):
        posts.append(load_md_post(path))
    # 새 글이 위로 오게. 같은 날짜면 id 가 큰 쪽이 나중 글
    posts.sort(key=lambda p: (p["date"], str(p["id"]).zfill(6)), reverse=True)
    return posts


# ---------------------------------------------------------------------------
# 분류
# ---------------------------------------------------------------------------
def slug_for(category: str, known: dict[str, str]) -> str:
    if category in known:
        return known[category]
    s = re.sub(r"[^a-z0-9]+", "-", category.lower()).strip("-")
    return s or f"cat-{zlib.crc32(category.encode()) % 10000}"


def group_by_category(posts: list[dict]) -> list[dict]:
    order = SITE.get("category_order", [])
    slugs = dict(SITE.get("category_slugs", {}))
    groups: dict[str, list[dict]] = defaultdict(list)
    for p in posts:
        groups[p["category"]].append(p)

    used: set[str] = set()
    cats = []
    for name, items in groups.items():
        slug = slug_for(name, slugs)
        while slug in used:
            slug += "-2"
        used.add(slug)
        cats.append({
            "name": name,
            "slug": slug,
            "posts": items,
            "count": len(items),
            "latest": items[0]["date"] if items else "",
            "url": f"category/{slug}.html",
        })
    cats.sort(key=lambda c: (order.index(c["name"]) if c["name"] in order else 999, -c["count"]))
    for p in posts:
        p["category_slug"] = next(c["slug"] for c in cats if c["name"] == p["category"])
        p["url"] = f"posts/{p['slug']}.html"
    return cats


def attach_neighbors(cats: list[dict]) -> None:
    """같은 과목 안에서 이전/다음 글 (목록은 최신순이므로 다음 글 = 더 옛날 글)."""
    for c in cats:
        items = c["posts"]
        for i, p in enumerate(items):
            p["newer"] = items[i - 1] if i > 0 else None
            p["older"] = items[i + 1] if i + 1 < len(items) else None


# ---------------------------------------------------------------------------
# 본문 후처리
# ---------------------------------------------------------------------------
HEADING_RE = re.compile(r"<(h[23])>(.*?)</\1>", re.S)


def add_heading_ids(body: str) -> tuple[str, list[dict]]:
    toc: list[dict] = []
    counter = [0]

    def repl(m):
        counter[0] += 1
        hid = f"s{counter[0]}"
        text = strip_text(m.group(2), 80)
        toc.append({"id": hid, "level": int(m.group(1)[1]), "text": text})
        return f'<{m.group(1)} id="{hid}">{m.group(2)}</{m.group(1)}>'

    return HEADING_RE.sub(repl, body), toc


def rewrite_image_paths(body: str, depth: int) -> str:
    """본문의 '../images/..' 를 출력 위치(docs/posts/) 기준 경로로 맞춘다. 이미지는 docs/images/ 에만 둔다."""
    prefix = "../" * depth
    return body.replace('src="../images/', f'src="{prefix}images/')


# ---------------------------------------------------------------------------
# 렌더링
# ---------------------------------------------------------------------------
def make_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["kdate"] = lambda d: d.replace("-", ".") if d else ""
    return env


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def copy_static() -> None:
    (OUT / "assets").mkdir(parents=True, exist_ok=True)
    for f in STATIC.iterdir():
        if f.is_file():
            shutil.copy2(f, OUT / "assets" / f.name)


def build(verbose: bool = True) -> dict:
    posts = load_posts()
    cats = group_by_category(posts)
    attach_neighbors(cats)
    env = make_env()

    if OUT.exists():
        # 이미지가 커서 매번 지우지 않고 덮어쓴다. 글/분류 페이지만 정리.
        for sub in ("posts", "category"):
            shutil.rmtree(OUT / sub, ignore_errors=True)
    OUT.mkdir(exist_ok=True)
    copy_static()

    ctx = {
        "site": SITE,
        "cats": cats,
        "total": len(posts),
        "built": date.today().isoformat(),
    }

    # 홈
    write(OUT / "index.html", env.get_template("index.html.j2").render(
        **ctx, root="", recent=posts[:12], page_title=None))

    # 과목 페이지
    for c in cats:
        write(OUT / c["url"], env.get_template("category.html.j2").render(
            **ctx, root="../", cat=c, page_title=c["name"]))

    # 글 페이지
    for p in posts:
        body, toc = add_heading_ids(p["body"])
        body = rewrite_image_paths(body, depth=1)
        # 수식이 있는 글에만 MathJax 를 싣는다. 가져온 글은 '$'가 금액 표기로도 쓰이므로
        # 단일 $ 인라인은 Markdown 으로 새로 쓴 글에서만 켠다.
        p["math_dollar"] = p["origin"] == "markdown"
        p["has_math"] = p["math_dollar"] or any(k in body for k in ("$$", "\\(", "\\["))
        write(OUT / p["url"], env.get_template("post.html.j2").render(
            **ctx, root="../", post=p, body=body, toc=toc, page_title=p["title"]))

    # 검색 색인 + 404
    index = [{
        "t": p["title"], "c": p["category"], "d": p["date"], "u": p["url"],
        "x": p["text"][:1500],
    } for p in posts]
    write(OUT / "search.json", json.dumps(index, ensure_ascii=False))
    write(OUT / "404.html", env.get_template("404.html.j2").render(**ctx, root="/", page_title="404"))
    write(OUT / ".nojekyll", "")

    if verbose:
        print(f"posts: {len(posts)}  categories: {len(cats)}")
        for c in cats:
            print(f"  {c['count']:>3}  {c['name']}  -> {c['url']}")
    return {"posts": len(posts), "categories": len(cats)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--serve", action="store_true", help="빌드 후 로컬 서버(8000) 실행")
    args = ap.parse_args()
    build()
    if args.serve:
        import functools
        import http.server
        import socketserver

        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(OUT))
        with socketserver.TCPServer(("", 8000), handler) as httpd:
            print("http://localhost:8000  (Ctrl+C 로 종료)")
            httpd.serve_forever()


if __name__ == "__main__":
    main()
