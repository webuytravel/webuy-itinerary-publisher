# webuy-itinerary-publisher

Planner 丢一份行程 **PDF 或 Word** 进来 → 行程结构和配图自动落到 Skybear 生产后台,
成为一个内容完整的**草稿**产品。上架那一下永远留给人。

产出的目标水准 = [www.webuytravel.sg](https://www.webuytravel.sg/group-tour/) 上已发布的产品页。

> **第一次上手** → **[docs/SETUP.md](docs/SETUP.md)**,装什么、配什么。
> 结论是:跑通主流程需要配置的密钥数量是**零**。
>
> **要动手上传** → **[docs/UPLOAD_RUNBOOK.md](docs/UPLOAD_RUNBOOK.md)**,一份册子从 PDF
> 到草稿的完整顺序,哪一步不能换位置、哪一步要停下来等人。
>
> **要知道为什么** → **[docs/DESIGN.md](docs/DESIGN.md)**,每条结论怎么验出来的。
> 尤其第 4 节的生产表单雷区和第 6 节的上传实录。

## 为什么是新仓库

前身 `skybear-uploader` 的 Skybear 自动化、PDF 抽图、图片规格化、去重逻辑都是验证过的,
本项目直接移植了它的 `lib/`(34 个测试原样通过)。开新仓库是因为:

1. `skybear-uploader` 属主是 `ctwang54-create`,不在 `webuytravel` org 下,协作和推送都别扭;
2. 本项目要新增 Word 输入、外部图源、Trip Item,以及阶段二的 AI Planner 回告——
   范围比「上传器」大一圈。

## 现状

五个产品**已端到端跑通并落到生产草稿态**(2026-08-13),全部 `Unpublished`:

| 产品 | Product Id | 备注 |
|---|---|---|
| WBCKWE 9D8N 贵州重庆 | 408 | 后续重算过缩略图与轮播 |
| WBCURC 13D11N 北疆包机 | 409 | 同上 |
| WBCHET 9D7N 山西内蒙 | 410 | |
| WBINC9 9D6N 宁夏沙漠与黄河 | 411 | 图库这一级 0 覆盖,全靠册子图 + 外部图源 |
| WBSZX1 7D6N 粤味八城美食 | 412 | 有同区域同主题在售产品可采图 |

Trip Item(景点卡)这一层已经补上,外部图源已接入,竖版轮播和 stock 原图重取都已入库。
未完成:Word 解析层、阶段二回告 AI Planner。

另有两本册子(WBJGX8、WBOHE1)**没有做**:它们的 type_code 下已存在
**已发布**的 wt_travel,逐条比对后确认讲的就是线上在售的 `tours/348` 和 `tours/122`。
那是内容刷新而不是新建,新建只会造出重复产品——见 DESIGN.md 第 6.5 节。

## 开发

```sh
pip install -r requirements.txt
python3 -m pytest tests/ -q
```

预期 `46 passed, 5 skipped`。

**任何密钥都不进仓库,而且主流程也不需要密钥**——Skybear 后台靠使用者自己浏览器
的登录态,找图走服务端已配好 key 的 `webuy-itinerary-mcp`。`.env` 只服务
`lib/existence_check.py` 这条旁路,不建也能跑完。详见 [docs/SETUP.md](docs/SETUP.md)。
