# crawler-service

内部公开信息采集服务，固定使用 `scrapling[fetchers]==0.4.9`。服务仅监听 `127.0.0.1:8010`，通过共享 Bearer Token 接受主后端任务；不得在 Nginx 配置公网代理。

## 运行组件

- `app.main:app`：任务 API，只负责鉴权、入队、查询和取消。
- `worker.py`：单进程 Redis worker，保证最多同时执行一个任务。
- Redis DB 2：保存最长 7 天的任务执行态。原始 HTML 不持久化。
- PostgreSQL：由主后端保存来源 URL、证据、哈希、置信度和人工审核结果。

## 已登记网站与字段

| Site key | 网站 | 用途 | 可进入人工审核的字段 |
|---|---|---|---|
| `baidu` | `baidu.com` | 仅发现公开 URL | 无，搜索摘要永不作为证据 |
| `bing` | `cn.bing.com` | 仅发现公开 URL | 无，搜索摘要永不作为证据 |
| `official` | 竞品/品牌公开官网 | 经营信息 | 营业时间、配置、机位数、面积、网费、套餐、充值、开业信息 |
| `58` | `58.com` | 公开商铺房源 | 月租、租金单价、面积、楼层、地址、发布时间 |
| `anjuke` | `anjuke.com` | 公开商铺房源 | 月租、租金单价、面积、楼层、地址、发布时间 |
| `fang` | `fang.com` | 公开商铺房源 | 月租、租金单价、面积、楼层、地址、发布时间 |
| `gov` | `*.gov.cn` | 政府公开信息 | 政策原文、文号、发布日期、发布机构 |

明确排除：大众点评、美团、企查查、天眼查、抖音、小红书和高德网页。高德仅继续使用官方 API。

真实上座率、月/年营收、消防是否合格、电力容量不由采集服务推测。房源展示为“元/㎡/天”时，只根据同页公开面积执行 `单价 × 面积 × 30` 的透明换算，并同时保存原始单价证据。

## 本地启动

```bash
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
scrapling install
cp .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8010
python worker.py
```

## 安全边界

- 仅允许 HTTP/HTTPS 和 80/443 端口。
- DNS 解析结果、逐跳重定向和 Chromium 子请求都会检查，私网、回环、链路本地、保留地址及云元数据地址会被拒绝。
- `robots.txt` 不可获取时按禁止处理。
- 不使用 Cookie，不登录，不处理验证码，不启用 Scrapling 的验证码或反爬绕过能力。
- HTTP 优先；正文不足时才使用普通 `DynamicFetcher` Chromium。
- 单任务最多 20 页、300 秒；每域名至少间隔 3 秒。

## 测试

```bash
PYTHONPATH=. pytest tests -q
```

Fixture 分别覆盖百度、Bing、竞品官网、58 同城、安居客、房天下、政府政策，以及 SSRF、robots、URL/证据去重、人工数据优先、取消和 Redis 重连边界。网站结构变化导致规则不匹配时返回空结果，不会猜测字段。
