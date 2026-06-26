import argparse
import json
from pathlib import Path
from typing import Any

from tag_builder import build_and_tag

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = PROJECT_DIR / "data"
APP_DATA_DIR = PROJECT_DIR / "app" / "data"
CHUNK_SIZE = 100
PARALLEL_CHUNKS = 5


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
        "links": post.get("links") or [],
        "images": post.get("images") or [],
    }


def write_chunks(normalized: list[dict[str, Any]], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    chunk_count = (len(normalized) + CHUNK_SIZE - 1) // CHUNK_SIZE
    chunk_files: list[str] = []
    for i in range(chunk_count):
        start = i * CHUNK_SIZE
        end = start + CHUNK_SIZE
        chunk_data = normalized[start:end]
        filename = f"posts_{i}.json"
        (output_dir / filename).write_text(json.dumps(chunk_data, ensure_ascii=False), encoding="utf-8")
        chunk_files.append(filename)
    manifest = {
        "total": len(normalized),
        "chunkCount": chunk_count,
        "chunkSize": CHUNK_SIZE,
        "chunks": chunk_files,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ChunkedOutput] {len(normalized)} posts -> {chunk_count} chunks ({chunk_files[0]}...{chunk_files[-1]})")
    return manifest_path


def build(input_dir: Path, output_dir: Path) -> int:
    rows = merge_rows(read_jsonl(input_dir / "index.jsonl") + collect_from_posts(input_dir / "posts"))
    valid = [r for r in rows if r.get("topic_id") and r.get("title")]
    if not valid:
        print(json.dumps({"posts": 0, "warning": "没有找到有效帖子数据"}, ensure_ascii=False))
        return 0
    tagged = build_and_tag(valid)
    normalized = [normalize_post(row) for row in tagged]
    write_chunks(normalized, output_dir)
    return len(normalized)


def main() -> int:
    parser = argparse.ArgumentParser(description="将爬虫输出转换为前端可加载的分片数据，并自动构建标签")
    parser.add_argument("--input-dir", help=f"爬虫输出目录（默认 {DEFAULT_INPUT_DIR}）")
    parser.add_argument("--output-dir", help=f"前端数据输出目录（默认 {APP_DATA_DIR}）")
    parser.add_argument("--rebuild-vocab", action="store_true", help="强制重新构建标签词库")
    args = parser.parse_args()
    input_dir = Path(args.input_dir) if args.input_dir else DEFAULT_INPUT_DIR
    output_dir = Path(args.output_dir) if args.output_dir else APP_DATA_DIR
    count = build(input_dir, output_dir)
    print(json.dumps({"posts": count, "input": str(input_dir), "output": str(output_dir)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
