# TRAE 论坛产品帖归档爬虫

这个项目用于限速归档 TRAE 官方中文社区大赛初赛专区中的用户产品页帖子。

## 设计要点

- 使用 Discourse 公开 JSON 端点，不模拟浏览器滚动。
- 分类页通过 `https://forum.trae.cn/c/38-category/40-category/40.json?page=N` 分页获取。
- 帖子详情通过 `https://forum.trae.cn/t/topic/{topic_id}.json` 获取。
- 默认跳过置顶帖、官方用户帖、公告/指南类标题、作者删除帖、看起来不像产品页的帖子。
- 默认每次请求前随机等待 2 到 5 秒，避免高频访问。
- 默认不下载图片，只保存图片 URL；需要下载时显式启用。

## 快速运行

```powershell
cd d:\python\trae_solo_workspace\trae_forum_scraper
python scrape_trae_forum.py --config config.example.json --max-pages 1 --max-topics 3
```

完整扫描：

```powershell
cd d:\python\trae_solo_workspace\trae_forum_scraper
python scrape_trae_forum.py --config config.example.json
```

更保守的限速：

```powershell
cd d:\python\trae_solo_workspace\trae_forum_scraper
python scrape_trae_forum.py --config config.example.json --min-delay 5 --max-delay 12
```

同时下载图片：

```powershell
cd d:\python\trae_solo_workspace\trae_forum_scraper
python scrape_trae_forum.py --config config.example.json --download-images --min-delay 5 --max-delay 12
```

## 输出结构

运行后默认写入 `data` 目录：

- `data/index.jsonl`：已保存帖子的索引，每行一个帖子。
- `data/skipped.jsonl`：被跳过的帖子与原因。
- `data/raw/{topic_id}.json`：帖子详情原始 JSON。
- `data/posts/{topic_id}_{title}.json`：结构化帖子数据。
- `data/posts/{topic_id}_{title}.txt`：便于阅读的纯文本。
- `data/posts/{topic_id}_{title}.html`：便于浏览器打开的 HTML。
- `data/images/{topic_id}/`：仅在启用 `--download-images` 后出现。

## 常用参数

```powershell
python scrape_trae_forum.py --help
```

重点参数：

- `--max-pages 2`：最多扫描 2 个分类分页。
- `--max-topics 20`：最多新增保存 20 个帖子。
- `--dry-run`：只扫描，不写入文件。
- `--include-official`：包含官方/置顶/公告类帖子。
- `--output-dir data_full`：指定输出目录。

## 产品浏览前端

爬虫数据可以包装成一个本地 HTML 推荐产品：

```powershell
cd d:\python\trae_solo_workspace\trae_forum_scraper
python build_app_data.py --input-dir data --output app/data/posts.json
python -m http.server 8000 -d app
```

然后打开：

```text
http://localhost:8000
```

如果只想用测试数据预览：

```powershell
cd d:\python\trae_solo_workspace\trae_forum_scraper
python build_app_data.py --input-dir data_test --output app/data/posts.json
python -m http.server 8000 -d app
```

前端特性：

- 类短视频单屏浏览，每一屏只展示一个帖子。
- 支持鼠标滚轮、键盘上下键、移动端触摸上下滑。
- 自动记录本机浏览器中的停留时间、浏览次数、感兴趣、跳过和详情跳转。
- 根据标签偏好、行为得分、新鲜度和帖子互动质量实时重排推荐流。
- 用户画像保存在浏览器 `localStorage`，可点击“重置偏好”清空。

## 过滤逻辑说明

默认会跳过：

1. 分类摘要中包含“话题已被作者删除”的帖子。
2. 置顶、全局置顶、featured 标签帖子。
3. 作者在 `official_usernames` 中的帖子。
4. 标题包含“公告、指南、必看、关于大赛、参赛指南”的帖子。
5. 不包含 Demo、作品、赛道、简介、产品、工具、应用、项目等产品帖特征，且没有赛道标签的帖子。

如果后续发现某些官方用户名或标题模式需要调整，修改 `config.example.json` 或复制一份 `config.json` 使用即可。
