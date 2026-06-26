import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

import jieba
import jieba.analyse

PROJECT_DIR = Path(__file__).resolve().parent
VOCAB_PATH = PROJECT_DIR / "data" / "tag_vocabulary.json"

STOP_WORDS = {
    "一个", "这个", "那个", "什么", "怎么", "如何", "可以", "进行", "通过",
    "使用", "基于", "实现", "提供", "支持", "包括", "以及", "用于", "相关",
    "主要", "核心", "特点", "方式", "方法", "系统", "平台", "产品",
    "项目", "工具", "应用", "服务", "用户", "场景", "方案", "技术",
    "需求", "问题", "目标", "方向", "领域", "行业", "市场", "内容", "数据",
    "信息", "管理", "设计", "开发", "创建", "生成", "完成", "需要", "能够",
    "已经", "当前", "传统", "全新", "简单", "快捷", "高效", "自动",
    "没有", "不是", "就是", "但是", "并且", "虽然", "因为", "所以",
    "如果", "或者", "比如", "例如", "包括", "以上", "以下",
    "demo", "Demo", "TRAE", "AI", "ai", "trae",
    "赛道", "初赛", "复赛", "决赛", "大赛", "专区", "作品", "报名",
    "附件", "图片", "截图", "链接", "地址", "文件", "尺寸", "下载",
    "编辑", "社交", "开发", "思考", "灵感", "上传",
    "面向", "一款", "就是", "网站", "网页", "希望", "形态", "点击",
    "打开", "手机", "同时", "桌面", "反馈", "体验", "快速", "界面",
    "输入", "输出", "展示", "完整", "实时", "建议", "时间", "最后",
    "需要", "只能", "更好", "选择", "自己", "目前", "帮助", "准备",
    "很多", "看到", "知道", "之后", "开始", "一起", "觉得", "因为",
    "发现", "进入", "不同", "带来", "成为", "之前", "出来", "起来",
    "最近", "还有", "的话", "这里", "是否", "从而", "仍然", "全新",
    "已有", "更多", "之后", "部分", "结合", "方面", "进入", "超过",
    "各种", "不同", "建立", "包含", "直接", "分别", "带来", "分成",
    "称作", "看到", "只有", "来到", "描述", "运行", "再次", "试试",
    "觉得", "真是", "算是", "确实", "不错", "有点", "看了", "看到",
    "许多", "一定", "或者", "仍然", "符合", "突出", "分为", "整个",
    "看看", "每个", "加入", "特别", "其中", "非常", "进入", "生成",
    "显示", "制作", "采用", "利用", "提供", "加入", "配合", "强大",
    "系列", "位于", "在线", "同步", "关于", "具有", "用于", "支持",
    "即可", "无需", "根据", "所有", "一句", "image1920", "homebrew",
}


def extract_demo_intro(text: str) -> str:
    if not text:
        return ""
    intro_match = re.search(
        r"(?:\d+|[一二三四五六七八九十]+)?[.、．\s]*Demo\s*简介[：:\s\n]*([\s\S]*?)"
        r"(?=\n\s*(?:(?:\d+|[一二三四五六七八九十]+)[.、．\s]*)?(?:Demo\s*创作思路|创作思路|"
        r"Demo\s*体验地址|体验地址|TRAE\s*实践过程|实践过程|开发思路|Session\s*ID|检查点|$))",
        text,
        re.IGNORECASE,
    )
    if intro_match:
        return intro_match.group(1).strip()
    return ""


def extract_title_text(title: str) -> str:
    if not title:
        return ""
    cleaned = re.sub(r"[【】\[\]《》（）()#\-—+_　]", " ", title)
    return cleaned.strip()


def segment_text(text: str) -> list[str]:
    words = jieba.lcut(text)
    result = []
    for w in words:
        w = w.strip().lower()
        if len(w) < 2:
            continue
        if re.match(r"^\d+$", w):
            continue
        if re.match(r"^[a-z]{1,2}$", w):
            continue
        if w in STOP_WORDS:
            continue
        result.append(w)
    return result


def extract_keywords(text: str, top_k: int = 20) -> list[str]:
    keywords = jieba.analyse.extract_tags(text, topK=top_k)
    return [k for k in keywords if k not in STOP_WORDS and len(k) >= 2]


class NaiveBayesClassifier:
    def __init__(self) -> None:
        self.tag_priors: dict[str, float] = {}
        self.word_probs: dict[str, dict[str, float]] = {}
        self.vocab: list[str] = []
        self.alpha: float = 1.0

    def train(self, posts: list[dict[str, Any]], tag_vocab: list[str]) -> None:
        self.vocab = list(set(tag_vocab))
        vocab_size = len(self.vocab)
        total_posts = len(posts)
        self.tag_priors = {}
        tag_positive_counts: dict[str, int] = {}
        tag_word_counts: dict[str, Counter] = {}

        for tag in self.vocab:
            tag_positive_counts[tag] = 0
            tag_word_counts[tag] = Counter()

        for post in posts:
            source_text = f"{extract_title_text(post.get('title', ''))} {extract_demo_intro(post.get('text', ''))}"
            words = set(segment_text(source_text))
            for tag in self.vocab:
                if tag in source_text:
                    tag_positive_counts[tag] += 1
                    for w in words:
                        if w in self.vocab:
                            tag_word_counts[tag][w] += 1

        for tag in self.vocab:
            pos_count = tag_positive_counts[tag]
            self.tag_priors[tag] = math.log((pos_count + 1) / (total_posts + len(self.vocab)))
            self.word_probs[tag] = {}
            total_words_for_tag = sum(tag_word_counts[tag].values()) + vocab_size
            for w in self.vocab:
                count_w = tag_word_counts[tag].get(w, 0)
                self.word_probs[tag][w] = math.log((count_w + self.alpha) / total_words_for_tag)

    def predict(self, words: list[str], top_k: int = 5) -> list[tuple[str, float]]:
        word_set = set(words)
        scores: list[tuple[str, float]] = []
        for tag in self.vocab:
            score = self.tag_priors.get(tag, 0.0)
            tag_probs = self.word_probs.get(tag, {})
            for w in self.vocab:
                if w in word_set:
                    score += tag_probs.get(w, math.log(self.alpha / 1))
                else:
                    score += math.log(1.0 - math.exp(tag_probs.get(w, math.log(self.alpha / 1))))
            scores.append((tag, score))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tag_priors": self.tag_priors,
            "word_probs": self.word_probs,
            "vocab": self.vocab,
            "alpha": self.alpha,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NaiveBayesClassifier":
        nb = cls()
        nb.tag_priors = data["tag_priors"]
        nb.word_probs = data["word_probs"]
        nb.vocab = data["vocab"]
        nb.alpha = data.get("alpha", 1.0)
        return nb


class TagBuilder:
    def __init__(self) -> None:
        self.tag_vocab: list[str] = []
        self.classifier = NaiveBayesClassifier()
        self.min_tag_freq = 2
        self.max_tags = 5

    def build_vocabulary(self, posts: list[dict[str, Any]]) -> list[str]:
        word_counter: Counter = Counter()
        doc_counter: Counter = Counter()
        for post in posts:
            title = extract_title_text(post.get("title", ""))
            intro = extract_demo_intro(post.get("text", ""))
            combined = f"{title} {intro}"
            words = set(segment_text(combined))
            for w in words:
                word_counter[w] += 1
            for w in words:
                doc_counter[w] += 1
        min_docs = max(2, int(len(posts) * 0.015))
        candidate_tags = [
            w
            for w, count in doc_counter.items()
            if count >= min_docs and w not in STOP_WORDS and len(w) >= 2 and not re.match(r"^\d+$", w)
        ]
        candidate_tags.sort(key=lambda w: (-doc_counter[w], -word_counter[w], len(w)))
        cutoff = min(120, max(30, int(len(candidate_tags) * 0.6)))
        self.tag_vocab = candidate_tags[:cutoff]
        return self.tag_vocab

    def train(self, posts: list[dict[str, Any]]) -> None:
        if not self.tag_vocab:
            self.build_vocabulary(posts)
        print(f"[TagBuilder] train with {len(posts)} posts, tag_vocab size={len(self.tag_vocab)}")
        self.classifier.train(posts, self.tag_vocab)
        print(f"[TagBuilder] training done, tags: {self.tag_vocab[:20]}...")

    def tag_post(self, post: dict[str, Any]) -> list[str]:
        title = extract_title_text(post.get("title", ""))
        intro = extract_demo_intro(post.get("text", ""))
        combined = f"{title} {intro}"
        words = segment_text(combined)
        matched_tags = [t for t in self.tag_vocab if t in combined]
        unique_matched = list(dict.fromkeys(self._rank_by_position(matched_tags, combined)))
        if len(unique_matched) >= self.max_tags:
            return unique_matched[: self.max_tags]
        if not self.classifier.vocab:
            return unique_matched[: self.max_tags] if unique_matched else ["未分类"]
        nb_tags = self.classifier.predict(words, top_k=self.max_tags)
        nb_tag_names = [t for t, _ in nb_tags if t not in unique_matched]
        result = unique_matched + nb_tag_names
        return result[: self.max_tags]

    def _rank_by_position(self, tags: list[str], source_text: str) -> list[str]:
        scored: list[tuple[str, int, int]] = []
        for tag in set(tags):
            idx = source_text.find(tag)
            freq = source_text.count(tag)
            scored.append((tag, idx if idx >= 0 else 9999, -freq))
        scored.sort(key=lambda x: (x[1], x[2]))
        return [t for t, _, _ in scored]

    def auto_tag(self, posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.tag_vocab or not self.classifier.vocab:
            self.build_vocabulary(posts)
            self.train(posts)
        result = []
        for post in posts:
            tags = self.tag_post(post)
            new_post = dict(post)
            new_post["tags"] = tags
            result.append(new_post)
        return result

    def save(self, path: str | Path | None = None) -> None:
        save_path = Path(path) if path else VOCAB_PATH
        data = {
            "tag_vocab": self.tag_vocab,
            "classifier": self.classifier.to_dict(),
            "min_tag_freq": self.min_tag_freq,
        }
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[TagBuilder] saved vocabulary to {save_path}")

    def load(self, path: str | Path | None = None) -> bool:
        load_path = Path(path) if path else VOCAB_PATH
        if not load_path.exists():
            print(f"[TagBuilder] vocabulary not found at {load_path}")
            return False
        data = json.loads(load_path.read_text(encoding="utf-8"))
        self.tag_vocab = data["tag_vocab"]
        self.classifier = NaiveBayesClassifier.from_dict(data["classifier"])
        self.min_tag_freq = data.get("min_tag_freq", 2)
        print(f"[TagBuilder] loaded vocabulary with {len(self.tag_vocab)} tags from {load_path}")
        return True


def build_and_tag(posts: list[dict[str, Any]], force_rebuild: bool = False) -> list[dict[str, Any]]:
    builder = TagBuilder()
    if not force_rebuild and builder.load():
        result = []
        for post in posts:
            tags = builder.tag_post(post)
            new_post = dict(post)
            new_post["tags"] = tags
            result.append(new_post)
        return result
    result = builder.auto_tag(posts)
    builder.save()
    return result


if __name__ == "__main__":
    from build_app_data import collect_from_posts, read_jsonl, merge_rows

    scraper_dir = PROJECT_DIR / "data"
    rows = merge_rows(read_jsonl(scraper_dir / "index.jsonl") + collect_from_posts(scraper_dir / "posts"))
    valid = [r for r in rows if r.get("topic_id") and r.get("title")]
    print(f"Total posts for tagging: {len(valid)}")
    tagged = build_and_tag(valid, force_rebuild=True)
    print("\n=== Sample tags ===")
    for p in tagged[:10]:
        print(f"  #{p['topic_id']} {p['title'][:40]:<40s} tags={p['tags']}")
    builder = TagBuilder()
    builder.load()
    untagged = [p for p in tagged if not p.get("tags")]
    few_tags = [p for p in tagged if len(p.get("tags", [])) < 1]
    print(f"\nUntagged: {len(untagged)}, <1 tag: {len(few_tags)}")
    print("All posts have tags:", all(len(p.get("tags", [])) >= 1 for p in tagged))
    print("All posts have ≤5 tags:", all(len(p.get("tags", [])) <= 5 for p in tagged))
    print("Tag vocabulary:", builder.tag_vocab[:40])
