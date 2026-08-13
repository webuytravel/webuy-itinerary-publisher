# 环境准备

先说结论:**跑通主流程需要配置的密钥数量是零。**

这句话不是省略,是实测。2026-08-13 用这套流程把 5 个产品送到 Skybear 生产草稿态
(product id 408–412),全程没有用到本仓库里的任何凭据。原因在下面这张表里。

---

## 三条访问路径,没有一条需要仓库里的密钥

| 要访问什么 | 靠什么 | 你要准备什么 |
|---|---|---|
| **Skybear 生产/UAT 后台** | 使用者**自己浏览器里的登录态** | 用你自己的账号登录 `travel.webuysg.com`,保持登录 |
| **找图**(Unsplash / Pexels / Gemini) | `webuy-itinerary-mcp` 服务端已配好 key | 什么都不用配 |
| **册子内嵌图** | 从 PDF 字节里直接抽 | 什么都不用配 |

### 为什么登录不能自动化

`docs/UPLOAD_RUNBOOK.md` 第 0 条:**登录由人做。** 这不是偷懒,是刻意的边界——
自动化流程不持有任何人的后台凭据,登录态过期就请人点一下 Login。这样这套东西在
谁的机器上跑,就只有那个人自己的权限,不会出现一份共享的管理员凭据在仓库里流转。

### 为什么图源 key 不在这里

`docs/DESIGN.md` 第 3 节:找图能力是通过 HTTP 调用已经部署的
`webuy-itinerary-mcp` 拿到的,Gemini / Unsplash / Pexels 的 key 全部在服务端。
**本项目一个 key 都不用配。**

> ⚠️ 已知问题:该 `/mcp` 端点当前**没有鉴权**——不带任何 Authorization 头就能完成
> 握手,意味着公网任何人都能消耗那套额度。这是一个独立于本项目的待修问题,
> `lib/mcp_photos.py` 里已经预留了 `WEBUY_MCP_TOKEN`,服务端配上之后设这个环境
> 变量即可,不需要改代码。

---

## `.env` 是可选的,而且只服务一条旁路

`.env.example` 里的 `SKYBEAR_RO_MYSQL_*` 只被 `lib/existence_check.py` 使用,
主管线(`bin/compose.py`、`bin/resharpen.py`、`bin/mobile_crops.py`、
`bin/make_payload.py`、`bin/review_page.py`)**一个都没引用**。

也就是说:**不建 `.env` 也能跑完整个流程。** 只有当你要直接查 Skybear 只读库时
才需要它,那时:

```bash
cp .env.example .env      # 然后填入你自己的只读库账号
```

那套账号是**按人发的**,不是共享凭据,请找 DBA 申请你自己的。
`.env` 在 `.gitignore` 里,不会被提交。

---

## 装依赖

```bash
pip install -r requirements.txt
```

`requirements.txt` 只有 PyMuPDF / Pillow / numpy / pymysql / python-dotenv /
certifi / pytest。跑一下测试确认环境正常:

```bash
python3 -m pytest tests -q
```

预期 `46 passed, 5 skipped`。

---

## 然后去读操作手册

环境就绪之后,**流程本身在 `docs/UPLOAD_RUNBOOK.md`**,按它走。那份文档记的是
「怎么做」,`docs/DESIGN.md` 记的是「每条结论怎么验出来的」。

两件事在开始之前就要知道:

1. **只到草稿态。** `Publish for sale` 永远不由程序勾选,上架那一下留给人。
   保存前必须回读 DOM 并截图确认它没被勾上——这个框的默认值实测不可预设。
2. **配图要人签字。** `bin/review_page.py` 出的审核页要有人看过并同意才往下走。
   外部图源的典型失败是「主体对、地方不对」(搜西夏陵返回兵马俑,搜驼车返回
   单峰驼 + 南亚服饰),这一关只能靠看图。

---

## 关于本仓库不包含的东西

这是一个**公开仓库**,所以它不包含、也不会包含:

- 任何真实凭据(数据库密码、API key、后台账号)
- 配图审核页(图片以 base64 内嵌,单个 6–9 MB;它们是签字留档,不进版本控制)
- `work/**/raw/`、`cand/`、`cat/`、`out/`、`out_mobile/` 等工作产物 —— 克隆下来
  是空的,跑一遍取图和 compose 就会重新生成

最后一条有个后果值得记住:**`OVERRIDES` 里写的是仓库相对路径,但相对路径不等于
文件存在。** 新检出直接跑 compose 会报错并列出全部缺失的源文件,那不是故障,
是提醒你还没跑取图步骤。
