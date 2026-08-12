# webuy-itinerary-publisher

Planner 丢一份行程 **PDF 或 Word** 进来 → 行程结构和配图自动落到 Skybear 生产后台,
成为一个内容完整的**草稿**产品。上架那一下永远留给人。

产出的目标水准 = [www.webuytravel.sg](https://www.webuytravel.sg/group-tour/) 上已发布的产品页。

> 设计依据、实测结论、已知缺口全部在 **[docs/DESIGN.md](docs/DESIGN.md)**。
> 动手前先读那份——尤其第 4 节的生产表单雷区和第 5 节的团期阻塞。

## 为什么是新仓库

前身 `skybear-uploader` 的 Skybear 自动化、PDF 抽图、图片规格化、去重逻辑都是验证过的,
本项目直接移植了它的 `lib/`(34 个测试原样通过)。开新仓库是因为:

1. `skybear-uploader` 属主是 `ctwang54-create`,不在 `webuytravel` org 下,协作和推送都别扭;
2. 本项目要新增 Word 输入、外部图源、Trip Item,以及阶段二的 AI Planner 回告——
   范围比「上传器」大一圈。

## 现状

阶段一进行中。已完成:`lib/` 移植 + 测试通过、目标形态实地核对、Word 样本实测、设计文档。
未完成:Word 解析层、外部图源接入、Trip Item、端到端跑通三个真实产品。

## 开发

```sh
pip install -r requirements.txt
python3 -m pytest tests/ -q
```

`.env.example` 复制成 `.env` 填 key。**任何密钥都不进仓库。**
