import argparse
import json
import re
from pathlib import Path
from typing import Any

from tag_builder import build_and_tag

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = PROJECT_DIR / "data"
DEFAULT_APP_DATA_PATH = PROJECT_DIR / "app" / "data" / "posts.json"

_AK_PATTERN = re.compile(r"q-ak=[^&]+|q-signature=[^&]+|q-key-time=[^&]+|q-sign-time=[^&]+", re.IGNORECASE)


def sanitize_image_url(url: str) -> str:
    stripped = _AK_PATTERN.sub("", url)
    stripped = re.sub(r"&{2,}", "&", stripped)
    stripped = re.sub(r"\?&+", "?", stripped)
    stripped = stripped.rstrip("?& ")
    return stripped if stripped else url


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def collect_from_posts(posts_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not posts_dir.exists():
        return rows
    for path in sorted(posts_dir.glob("*.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return rows


def merge_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    for row in rows:
        topic_id = row.get("topic_id")
        if isinstance(topic_id, int):
            merged[topic_id] = row
    return sorted(merged.values(), key=lambda item: item.get("topic_id") or 0, reverse=True)


def normalize_post(post: dict[str, Any]) -> dict[str, Any]:
    text = str(post.get("text") or "")
    summary = "\n".join(text.splitlines()[:12])
    images = post.get("images") or []
    links = post.get("links") or []
    return {
        "topic_id": post.get("topic_id"),
        "title": post.get("title"),
        "url": post.get("url"),
        "author": post.get("author"),
        "created_at": post.get("created_at"),
        "tags": post.get("tags") or [],
        "views": post.get("views") or 0,
        "like_count": post.get("like_count") or 0,
        "vote_count": post.get("vote_count") or 0,
        "reply_count": post.get("reply_count") or 0,
        "text": text,
        "summary": summary,
        "links": [{"href": sanitize_image_url(item.get("href", "")), "text": item.get("text", "")} for item in links],
        "images": [{"src": sanitize_image_url(item.get("src", "")), "alt": item.get("alt", ""), "title": item.get("title", "")} for item in images],
    }


def build(input_dir: Path, output_path: Path) -> int:
    rows = merge_rows(read_jsonl(input_dir / "index.jsonl") + collect_from_posts(input_dir / "posts"))
    valid = [r for r in rows if r.get("topic_id") and r.get("title")]
    if not valid:
        print(json.dumps({"posts": 0, "warning": "没有找到有效帖子数据"}, ensure_ascii=False))
        return 0
    tagged = build_and_tag(valid)
    normalized = [normalize_post(row) for row in tagged]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(normalized)


def main() -> int:
    parser = argparse.ArgumentParser(description="将爬虫输出转换为前端可加载的 posts.json，并自动构建标签")
    parser.add_argument("--input-dir", help=f"爬虫输出目录（默认 {DEFAULT_INPUT_DIR}）")
    parser.add_argument("--output", help=f"前端数据输出路径（默认 {DEFAULT_APP_DATA_PATH}）")
    parser.add_argument("--rebuild-vocab", action="store_true", help="强制重新构建标签词库")
    args = parser.parse_args()
    input_dir = Path(args.input_dir) if args.input_dir else DEFAULT_INPUT_DIR
    output_path = Path(args.output) if args.output else DEFAULT_APP_DATA_PATH
    count = build(input_dir, output_path)
    print(json.dumps({"posts": count, "input": str(input_dir), "output": str(output_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
