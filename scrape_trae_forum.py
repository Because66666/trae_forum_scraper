import argparse
import hashlib
import html
import json
import random
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

BASE_URL = "https://forum.trae.cn"
DEFAULT_CATEGORY_URL = "https://forum.trae.cn/c/38-category/40-category/40"
PROJECT_DIR = Path(__file__).resolve().parent
SCRAPER_OUTPUT_DIR = PROJECT_DIR / "data"
DELETED_MARKERS = ("话题已被作者删除", "topic has been deleted", "post deleted")
OFFICIAL_TITLE_MARKERS = ("公告", "指南", "必看", "关于大赛", "参赛指南")
PRODUCT_HINTS = ("Demo", "demo", "作品", "赛道", "简介", "产品", "工具", "应用", "项目")


@dataclass
class ScraperConfig:
    category_url: str = DEFAULT_CATEGORY_URL
    output_dir: str = str(SCRAPER_OUTPUT_DIR)
    min_delay: float = 2.0
    max_delay: float = 5.0
    timeout: int = 30
    max_retries: int = 3
    download_images: bool = False
    skip_official: bool = True
    official_usernames: tuple[str, ...] = ("TRAE-小阳", "博士哥", "汤圆")


class CookedHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self.images: list[dict[str, str]] = []
        self._current_link: str | None = None
        self._current_link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {key: value or "" for key, value in attrs}
        if tag == "a":
            self._current_link = attrs_map.get("href")
            self._current_link_text = []
        elif tag == "img":
            src = attrs_map.get("src")
            if src:
                self.images.append(
                    {
                        "src": urljoin(BASE_URL, src),
                        "alt": attrs_map.get("alt", ""),
                        "title": attrs_map.get("title", ""),
                    }
                )
        elif tag in {"p", "br", "div", "li", "blockquote", "h1", "h2", "h3", "h4", "hr"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current_link:
            text = "".join(self._current_link_text).strip()
            self.links.append({"href": urljoin(BASE_URL, self._current_link), "text": text})
            self._current_link = None
            self._current_link_text = []
        elif tag in {"p", "div", "li", "blockquote", "h1", "h2", "h3", "h4"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.text_parts.append(data)
        if self._current_link is not None:
            self._current_link_text.append(data)

    def get_text(self) -> str:
        text = html.unescape("".join(self.text_parts))
        lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line)


class TraeForumScraper:
    def __init__(self, config: ScraperConfig, dry_run: bool = False) -> None:
        self.config = config
        self.dry_run = dry_run
        self.output_dir = Path(config.output_dir)
        self.raw_dir = self.output_dir / "raw"
        self.posts_dir = self.output_dir / "posts"
        self.images_dir = self.output_dir / "images"
        self.index_path = self.output_dir / "index.jsonl"
        self.skipped_path = self.output_dir / "skipped.jsonl"
        self.ua = "TraeForumProductArchiver/1.0 (+respectful rate limited public archive)"

    def run(self, max_pages: int | None = None, max_topics: int | None = None, crawl_all: bool = False) -> dict[str, int]:
        self.prepare_dirs()
        saved_ids = self.load_saved_topic_ids()
        newest_saved_id = max(saved_ids) if saved_ids else None
        topics, reached_existing_floor = self.discover_topics(max_pages=max_pages, newest_saved_id=newest_saved_id, crawl_all=crawl_all)
        stats = {
            "discovered": len(topics),
            "saved": 0,
            "skipped": 0,
            "existing": 0,
            "failed": 0,
            "newest_saved_id": newest_saved_id or 0,
            "stopped_at_existing_floor": int(reached_existing_floor),
        }
        for topic in topics:
            topic_id = topic.get("id")
            if not isinstance(topic_id, int):
                continue
            if topic_id in saved_ids:
                stats["existing"] += 1
                continue
            if max_topics is not None and stats["saved"] >= max_topics:
                break
            decision = self.should_skip_topic_summary(topic)
            if decision:
                self.write_jsonl(self.skipped_path, {"topic_id": topic_id, "title": topic.get("title"), "reason": decision})
                stats["skipped"] += 1
                continue
            try:
                topic_data = self.fetch_json(f"{BASE_URL}/t/topic/{topic_id}.json")
                decision = self.should_skip_topic_detail(topic, topic_data)
                if decision:
                    self.write_jsonl(self.skipped_path, {"topic_id": topic_id, "title": topic.get("title"), "reason": decision})
                    stats["skipped"] += 1
                    continue
                record = self.build_record(topic, topic_data)
                if not self.dry_run:
                    self.save_record(record, topic_data)
                self.write_jsonl(self.index_path, record)
                saved_ids.add(topic_id)
                stats["saved"] += 1
                print(f"saved {topic_id}: {record['title']}")
            except Exception as exc:
                stats["failed"] += 1
                self.write_jsonl(self.skipped_path, {"topic_id": topic_id, "title": topic.get("title"), "reason": f"failed: {exc}"})
                print(f"failed {topic_id}: {exc}", file=sys.stderr)
        return stats

    def prepare_dirs(self) -> None:
        if self.dry_run:
            return
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.posts_dir.mkdir(parents=True, exist_ok=True)
        if self.config.download_images:
            self.images_dir.mkdir(parents=True, exist_ok=True)

    def discover_topics(self, max_pages: int | None = None, newest_saved_id: int | None = None, crawl_all: bool = False) -> tuple[list[dict[str, Any]], bool]:
        topics: list[dict[str, Any]] = []
        page = 1
        seen: set[int] = set()
        reached_existing_floor = False
        while True:
            if not crawl_all and max_pages is not None and page > max_pages:
                break
            url = self.category_json_url(page)
            data = self.fetch_json(url)
            topic_list = data.get("topic_list", {})
            page_topics = topic_list.get("topics", [])
            if not page_topics:
                break
            for topic in page_topics:
                topic_id = topic.get("id")
                if not isinstance(topic_id, int) or topic_id in seen:
                    continue
                if not crawl_all and newest_saved_id is not None and topic_id <= newest_saved_id:
                    reached_existing_floor = True
                    break
                seen.add(topic_id)
                topics.append(topic)
            if not crawl_all and (reached_existing_floor or not topic_list.get("more_topics_url")):
                break
            if crawl_all and not topic_list.get("more_topics_url"):
                break
            page += 1
        return topics, reached_existing_floor

    def category_json_url(self, page: int) -> str:
        parsed = urlparse(self.config.category_url)
        path = parsed.path.rstrip("/")
        if path.endswith(".json"):
            base = f"{parsed.scheme}://{parsed.netloc}{path}"
        else:
            base = f"{parsed.scheme}://{parsed.netloc}{path}.json"
        return f"{base}?page={page}"

    def fetch_json(self, url: str) -> dict[str, Any]:
        body = self.fetch_bytes(url)
        return json.loads(body.decode("utf-8"))

    def fetch_bytes(self, url: str) -> bytes:
        last_error: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            self.sleep_before_request()
            request = Request(url, headers={"User-Agent": self.ua, "Accept": "application/json,text/html;q=0.8,*/*;q=0.5"})
            try:
                with urlopen(request, timeout=self.config.timeout) as response:
                    return response.read()
            except HTTPError as exc:
                last_error = exc
                if exc.code in {429, 500, 502, 503, 504} and attempt < self.config.max_retries:
                    retry_after = exc.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after and retry_after.isdigit() else self.config.max_delay * attempt
                    time.sleep(delay)
                    continue
                raise
            except URLError as exc:
                last_error = exc
                if attempt < self.config.max_retries:
                    time.sleep(self.config.max_delay * attempt)
                    continue
                raise
        raise RuntimeError(f"request failed: {last_error}")

    def sleep_before_request(self) -> None:
        if self.config.max_delay <= 0:
            return
        low = max(0.0, self.config.min_delay)
        high = max(low, self.config.max_delay)
        time.sleep(random.uniform(low, high))

    def should_skip_topic_summary(self, topic: dict[str, Any]) -> str | None:
        title = str(topic.get("title") or "")
        excerpt = str(topic.get("excerpt") or "")
        tags = [tag.get("name") for tag in topic.get("tags") or [] if isinstance(tag, dict)]
        if topic.get("pinned") or topic.get("pinned_globally"):
            return "official_or_pinned"
        if any(marker in excerpt for marker in DELETED_MARKERS):
            return "deleted"
        if self.config.skip_official and any(marker in title for marker in OFFICIAL_TITLE_MARKERS):
            return "official_title"
        if "featured" in tags:
            return "featured_or_official"
        if not self.looks_like_product(title, excerpt, tags):
            return "not_product_like"
        return None

    def should_skip_topic_detail(self, topic: dict[str, Any], topic_data: dict[str, Any]) -> str | None:
        posts = topic_data.get("post_stream", {}).get("posts", [])
        if not posts:
            return "no_posts"
        first_post = posts[0]
        cooked = str(first_post.get("cooked") or "")
        text = self.parse_cooked(cooked)["text"]
        username = str(first_post.get("username") or "")
        if any(marker in text for marker in DELETED_MARKERS):
            return "deleted"
        if self.config.skip_official and username in set(self.config.official_usernames):
            return "official_author"
        title = str(topic.get("title") or topic_data.get("title") or "")
        tags = [tag.get("name") for tag in topic.get("tags") or [] if isinstance(tag, dict)]
        if not self.looks_like_product(title, text, tags):
            return "not_product_like"
        return None

    def looks_like_product(self, title: str, text: str, tags: list[str]) -> bool:
        combined = f"{title}\n{text}"
        if tags and any(tag in {"学习工作", "生活娱乐", "社会服务", "社会公益", "硬件交互"} for tag in tags):
            return True
        return any(hint in combined for hint in PRODUCT_HINTS)

    def build_record(self, topic: dict[str, Any], topic_data: dict[str, Any]) -> dict[str, Any]:
        posts = topic_data.get("post_stream", {}).get("posts", [])
        first_post = posts[0]
        parsed = self.parse_cooked(str(first_post.get("cooked") or ""))
        topic_id = int(topic.get("id") or topic_data.get("id"))
        tags = [tag.get("name") for tag in topic.get("tags") or [] if isinstance(tag, dict)]
        image_urls = self.collect_image_urls(topic, parsed["images"])
        record = {
            "topic_id": topic_id,
            "title": topic.get("title") or topic_data.get("title"),
            "url": f"{BASE_URL}/t/topic/{topic_id}",
            "author": first_post.get("username"),
            "created_at": first_post.get("created_at") or topic.get("created_at"),
            "last_posted_at": topic.get("last_posted_at"),
            "tags": tags,
            "views": topic.get("views"),
            "like_count": topic.get("like_count"),
            "vote_count": topic.get("vote_count"),
            "reply_count": topic.get("reply_count"),
            "text": parsed["text"],
            "links": parsed["links"],
            "images": image_urls,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        return record

    def parse_cooked(self, cooked: str) -> dict[str, Any]:
        parser = CookedHTMLParser()
        parser.feed(cooked)
        return {"text": parser.get_text(), "links": parser.links, "images": parser.images}

    def collect_image_urls(self, topic: dict[str, Any], images: list[dict[str, str]]) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in images:
            src = item.get("src")
            if src and src not in seen:
                seen.add(src)
                results.append(item)
        for thumb in topic.get("thumbnails") or []:
            if not isinstance(thumb, dict):
                continue
            url = thumb.get("url")
            if url and url not in seen:
                seen.add(url)
                results.append({"src": url, "alt": "", "title": ""})
        return results

    def save_record(self, record: dict[str, Any], topic_data: dict[str, Any]) -> None:
        topic_id = record["topic_id"]
        slug = self.safe_slug(str(record["title"] or topic_id))
        stem = f"{topic_id}_{slug}"
        (self.raw_dir / f"{topic_id}.json").write_text(json.dumps(topic_data, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.posts_dir / f"{stem}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.posts_dir / f"{stem}.txt").write_text(self.render_text(record), encoding="utf-8")
        (self.posts_dir / f"{stem}.html").write_text(self.render_html(record), encoding="utf-8")
        if self.config.download_images:
            self.download_images(record)

    def render_text(self, record: dict[str, Any]) -> str:
        links = "\n".join(f"- {item.get('text') or item.get('href')}: {item.get('href')}" for item in record["links"])
        images = "\n".join(f"- {item.get('src')}" for item in record["images"])
        return (
            f"标题：{record['title']}\n"
            f"链接：{record['url']}\n"
            f"作者：{record['author']}\n"
            f"发布时间：{record['created_at']}\n"
            f"标签：{', '.join(record['tags'])}\n\n"
            f"正文：\n{record['text']}\n\n"
            f"链接：\n{links}\n\n"
            f"图片：\n{images}\n"
        )

    def render_html(self, record: dict[str, Any]) -> str:
        body = html.escape(record["text"]).replace("\n", "<br>\n")
        links = "\n".join(
            f"<li><a href=\"{html.escape(item.get('href', ''))}\">{html.escape(item.get('text') or item.get('href', ''))}</a></li>"
            for item in record["links"]
        )
        images = "\n".join(
            f"<li><a href=\"{html.escape(item.get('src', ''))}\">{html.escape(item.get('src', ''))}</a></li>" for item in record["images"]
        )
        return (
            "<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\">"
            f"<title>{html.escape(str(record['title']))}</title>"
            "<body>"
            f"<h1>{html.escape(str(record['title']))}</h1>"
            f"<p><a href=\"{html.escape(record['url'])}\">原帖</a> · 作者：{html.escape(str(record['author']))}</p>"
            f"<p>标签：{html.escape(', '.join(record['tags']))}</p>"
            f"<article>{body}</article>"
            f"<h2>链接</h2><ul>{links}</ul>"
            f"<h2>图片</h2><ul>{images}</ul>"
            "</body></html>"
        )

    def download_images(self, record: dict[str, Any]) -> None:
        topic_dir = self.images_dir / str(record["topic_id"])
        topic_dir.mkdir(parents=True, exist_ok=True)
        for item in record["images"]:
            src = item.get("src")
            if not src:
                continue
            suffix = Path(urlparse(src).path).suffix or ".bin"
            name = hashlib.sha1(src.encode("utf-8")).hexdigest()[:16] + suffix
            target = topic_dir / name
            if target.exists():
                continue
            try:
                target.write_bytes(self.fetch_bytes(src))
            except Exception as exc:
                print(f"image failed {src}: {exc}", file=sys.stderr)

    def load_saved_topic_ids(self) -> set[int]:
        saved: set[int] = set()
        if self.index_path.exists():
            for line in self.index_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    topic_id = json.loads(line).get("topic_id")
                    if isinstance(topic_id, int):
                        saved.add(topic_id)
                except json.JSONDecodeError:
                    continue
        if self.raw_dir.exists():
            for path in self.raw_dir.glob("*.json"):
                try:
                    saved.add(int(path.stem))
                except ValueError:
                    continue
        if self.posts_dir.exists():
            for path in self.posts_dir.glob("*.json"):
                match = re.match(r"(\d+)_", path.stem)
                if match:
                    saved.add(int(match.group(1)))
        return saved

    def write_jsonl(self, path: Path, data: dict[str, Any]) -> None:
        if self.dry_run:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(data, ensure_ascii=False) + "\n")

    def safe_slug(self, text: str, max_length: int = 80) -> str:
        slug = re.sub(r"[\\/:*?\"<>|\s]+", "_", text).strip("_")
        return slug[:max_length] or "topic"


def load_config(path: str | None) -> ScraperConfig:
    if not path:
        return ScraperConfig()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data.get("official_usernames"), list):
        data["official_usernames"] = tuple(data["official_usernames"])
    return ScraperConfig(**data)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="限速归档 TRAE 论坛大赛专区用户产品帖")
    parser.add_argument("--config", help="配置文件路径，例如 config.example.json")
    parser.add_argument("--category-url", help="分类页 URL")
    parser.add_argument("--max-pages", type=int, help="最多扫描分类页数")
    parser.add_argument("--max-topics", type=int, help="最多保存帖子数")
    parser.add_argument("--min-delay", type=float, help="请求前最小随机等待秒数")
    parser.add_argument("--max-delay", type=float, help="请求前最大随机等待秒数")
    parser.add_argument("--download-images", action="store_true", help="下载帖子图片到本地")
    parser.add_argument("--include-official", action="store_true", help="不跳过官方用户或公告类帖子")
    parser.add_argument("--crawl-all", action="store_true", help="全量爬取：扫描所有页面，跳过已有数据（覆盖 --max-pages 和 --max-topics）")
    parser.add_argument("--dry-run", action="store_true", help="只扫描不写入文件")
    return parser.parse_args()


def apply_overrides(config: ScraperConfig, args: argparse.Namespace) -> ScraperConfig:
    data = asdict(config)
    data["output_dir"] = str(SCRAPER_OUTPUT_DIR)
    for key in ("category_url", "min_delay", "max_delay"):
        value = getattr(args, key)
        if value is not None:
            data[key] = value
    if args.download_images:
        data["download_images"] = True
    if args.include_official:
        data["skip_official"] = False
    data["official_usernames"] = tuple(data["official_usernames"])
    return ScraperConfig(**data)


def main() -> int:
    args = parse_args()
    config = apply_overrides(load_config(args.config), args)
    scraper = TraeForumScraper(config, dry_run=args.dry_run)
    max_pages = None if args.crawl_all else args.max_pages
    max_topics = None if args.crawl_all else args.max_topics
    stats = scraper.run(max_pages=max_pages, max_topics=max_topics, crawl_all=args.crawl_all)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
