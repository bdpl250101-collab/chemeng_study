# 화학공학 노트

티스토리 블로그(chem Audio)의 글을 가져와 만든 개인 화학공학 사이트.
정적 HTML 이라 GitHub Pages 에 그대로 올라가고, 새 글은 Markdown 으로 쓴다.

## 구조

```
site.json                  사이트 제목·과목 순서·URL 슬러그
content/posts/<id>.json    티스토리에서 가져온 글 (본문 HTML + 메타)
content/posts/*.md         새로 쓰는 글 (Markdown + front matter)
docs/images/<id>/          글 이미지 (카카오 CDN 에서 내려받은 사본, 이곳 하나만 둔다)
templates/*.j2             페이지 템플릿 (Jinja2)
static/style.css, app.js   스타일 · 검색 · 정렬
build.py                   content -> docs 빌드
tools/import_tistory.py    티스토리 가져오기
docs/                      빌드 결과 = GitHub Pages 배포 루트
.github/workflows/build.yml  push 시 docs 자동 재생성
```

## 로컬에서 보기

```bash
pip install -r requirements.txt
python build.py --serve        # http://localhost:8000
```

## 새 글 쓰기

`content/posts/` 에 `.md` 파일을 만든다. 파일 이름이 URL 이 된다 (예: `mccabe-thiele.md` → `posts/mccabe-thiele.html`).

```markdown
---
title: McCabe-Thiele 작도법 정리
date: 2026-10-01
category: 분리공정
tags: [증류, 단수 계산]
---

본문. 수식은 인라인 $x_D$, 블록은

$$ R_{min} = \frac{x_D - y'}{y' - x'} $$

이미지는 `docs/images/<폴더>/파일.png` 에 넣고 `../images/<폴더>/파일.png` 로 참조한다.
```

과목(category)은 `site.json` 의 `category_order` 에 있는 이름을 쓰면 그 순서로 정렬되고,
없는 이름을 쓰면 새 과목이 자동으로 생긴다.

## 티스토리에서 새 글 추가로 가져오기

```bash
python tools/import_tistory.py --start 302      # 302번 이후 글만
python tools/import_tistory.py --ids 310 311    # 특정 글만
python build.py
```

비공개 글(403)은 가져올 수 없다. 티스토리에서 공개로 바꾼 뒤 다시 실행하면 된다.

## 배포 (GitHub Pages, 최초 1회)

1. GitHub 에 저장소를 만들고 push
2. **Settings → Pages → Source: "Deploy from a branch" → `main` / `/docs`**
3. 이후 `content/`, `templates/`, `static/` 을 고쳐 push 하면 Actions 가 `docs/` 를 다시 만들어 커밋하고 Pages 에 반영된다.
   로컬에서 `python build.py` 를 돌려 `docs/` 까지 같이 커밋해도 된다.

## 검색

`docs/search.json` 에 제목·과목·본문 앞부분이 들어 있고, 상단 검색창에서 브라우저 안에서만 검색한다 (서버 없음).
키보드 `/` 로 검색창에 바로 들어간다.
