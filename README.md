# 值班简报

给客户跑的订阅服务：客户说要盯什么，我每天早上给一份说人话的简报。

机器负责不漏，人负责判断。

## 它现在能干什么

- 从一个或多个 RSS/Atom 源抓条目，按关键词筛、跨源去重、按时间窗截取
- 盯一个网页上的单个值（价格、库存、版本号、某个计数），变了才报，没变说没变
- 一个客户一个配置文件，加客户不用改代码

## 用法

```bash
pip install requests
python3 brief.py clients/sample-ai.json --hours 24
```

产出写到 `out/`，同时打到标准输出。

### 客户配置

```json
{
  "name": "样例客户 · AI 行业",
  "slug": "sample-ai",
  "hours": 20,
  "sources": [
    {"type": "rss", "name": "OpenAI 官方", "url": "https://openai.com/news/rss.xml", "limit": 5},
    {"type": "rss", "name": "Hacker News", "url": "https://hnrss.org/frontpage",
     "keywords": ["ai", "llm", "agent"], "limit": 8},
    {"type": "watch", "name": "某商品价", "url": "https://example.com/item",
     "regex": "\\$([0-9.]+)", "label": " 美元"}
  ]
}
```

- `keywords` 省了就是不过滤，按词边界匹配（`ai` 不会命中 `air traffic`）
- `watch` 类型第一次跑建立基线，之后只在变化时提示

## 拿到什么

`out/` 里是机器出的候选池：标题、时间、链接。

给人看的那一版不是它——是有人读完之后，每条补一句「发生了什么、跟你什么关系」。样例见 `examples/样张-1108.md`。

这条分工是刻意的：客户买的是判断，不是链接列表。

## 已知不足

- RSS 用正则解析，没上 feedparser，Atom 多 link 时可取错
- 没有测试
- 单进程，state 文件并发写会打架

## 路线

见 `ROADMAP.md`。
