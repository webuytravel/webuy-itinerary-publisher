# `work/<CODE>/editorial.json` —— 一个产品的编辑决策

做一本册子会产生一批**只对这个产品成立的判断**:六条 highlights 怎么取舍、
哪一天用哪张图、轮播八格放什么、景点卡从哪一级图源取、GPS 范围框画多大。
它们全部写在这一个文件里,和 `itinerary.json` / `plan.json` 同级。

**跑一本新册子不再需要改 `bin/` 下的任何代码。** 这是 issue #4 要的结果:
原来这些决策是 5 个脚本里 8 张以产品代码为键的字典(约 1352 行),
业务同事跑一遍就要有工程跟在后面提交代码,两个人同时做两本册子会改到
同一个字典的相邻行。

**为什么不做成一个集中的大文件。** 集中式只是把合并冲突原样搬过去。
跟着产品走,两个人做两本册子改的是两个文件,谁也不挡谁。

---

## 谁读它

| 脚本 | 读哪几个字段 |
|---|---|
| `bin/fetch_commons.py` | `commons_region_box` |
| `bin/fetch_stock.py` | `stock_region` |
| `bin/compose.py` | `region`、`catalogue_tours`、`section_overrides`、`trip_picks`、`carousel`;**还靠它决定有哪些产品** |
| `bin/make_payload.py` | `highlights` |
| `bin/make_api_payload.py` | `highlights`、`meals`、`trip_types` |

读取和校验都在 `lib/editorial.py`。

---

## 字段

```jsonc
{
  "code": "WBLJG9",            // 必填,要和目录名一致
  "region": "CHN",             // 必填

  // 每个字段的「为什么是这样」。JSON 没有注释语法,所以原来写在字典上面的
  // 那几行说明落在这里,按它注解的字段分组。
  "notes": {
    "catalogue_tours": ["webuytravel.sg 上没有同区域在售的云南产品可采,①② 两级都是空的"]
  },

  // ②图库这一级可采的兄弟产品。没有就写 []。空数组还有一个副作用:
  // compose 的跨槽去重会关掉(`cross_slot=bool(tours)`),因为没有剩图可补。
  "catalogue_tours": ["tours/4-8d7n-yunan-dali-lijiang-shangri-la"],

  // ③Commons 的 GPS 范围框,[lat_min, lat_max, lon_min, lon_max]。
  // 全管线唯一一道「主体对、地方不对」的机械检查(DESIGN 3.2 / 6.7)。
  // 宁可画宽:它只需要把「这条行程上」和「另一个大洲」分开。
  "commons_region_box": [24, 29, 98, 103],

  // ④stock 搜索带的地区词。省 + 国家就够,写到县只会把松散排序的索引搜窄。
  // 不写退回 "China"。
  "stock_region": "Yunnan China",

  // 表单/接口的六行 highlights。6 是房子版式不是限制(UPLOAD_RUNBOOK 第 5 步
  // 第 4 条):四条头部景点/体验 + 一条 `·` 压缩的次级景点 + 一条餐食。
  // 中文的键是 zh 不是 cn。
  "highlights": [{"en": "…", "zh": "…", "why": "可选,这一条为什么这么取舍"}],

  // 逐日餐食,册子页脚抄下来的。只有走接口那条路(make_api_payload)要。
  // 一餐都不含的那天写 "-",不是描述吃了什么。
  "meals": {"1": {"en": "-", "zh": "-"}},

  // 逐条 Trip Type,键是「天:当天第几条」(从 0 数)。没列出来的一律
  // ATTRACTION。可用:TRANSPORT / ACCOMMODATION / ATTRACTION / OTHERS /
  // FOOD / LOCAL_TRANSPORT / GUIDE。
  "trip_types": {"4:2": "FOOD"},

  // 逐日的 section 配图。**有 override 的那天会整天跳过自动匹配**,
  // 所以要么不写这一天,要么把这一天要的都写全。
  "section_overrides": {
    "d02": [{"source": "stock", "block": "d02_dali_ancient_city", "n": 4,
             "note": "大理城楼夜景,金光 s0.864"}]
  },

  // 景点卡专用的选片。这些不会自己进 plan —— 只有当某张景点卡的主体匹配上
  // 才会进(分开的理由见 DESIGN 1.1)。
  "trip_picks": [{"source": "commons", "block": "d06_hanging_temple_hunyuan",
                  "n": 1, "note": "崖壁全景,绿 s0.26"}],

  // 显式指定的轮播八格。**不写这个字段**和写成 `[]` 是两件事:
  // 不写 = 从图库剩图里自动补;`[]` = 这个产品的轮播明确留空。
  "carousel": [{"source": "cat", "image_id": "YAJzGm1f", "note": "虎跳峡另一机位"}]
}
```

### 一条选片怎么写

| `source` | 指向哪里 | 要带的字段 | 能用在 |
|---|---|---|---|
| `stock` | `work/<CODE>/candidates.json` 的 `block` 第 `n` 张 | `block`, `n` | section / trip / carousel |
| `commons` | `work/<CODE>/commons.json` 的 `block` 第 `n` 张 | `block`, `n` | section / trip |
| `cat` | `work/catalogue.json` 里的 `image_id` | `image_id` | section / carousel |
| `file` | 仓库里的一个具体文件 | `path` | section |

每条还可以带 `note`(会显示在配图审核页上)和 `why`(写给读代码的人,
比如「换掉原来的 #3/#5/#6,那三张 s0.11–0.16 是灰崖壁」)。

**景点卡不收 `cat`**:图库图走的是自动匹配那条路。
**轮播不收 `commons`**:轮播竖版要 1080px 以上,Commons 那一级尺寸不稳。

---

## 指错了要炸

这是这份格式最重要的性质,不是附带的。**打错一个键名或序号必须在读取/解析
那一刻退出,不许静默跳过。** `docs/DESIGN.md` 6.9 / 6.11 记的两次静默降级
就是这么来的:一个打错的 block 名被 `if row:` 静默跳过,那天无声地少一张图,
而摘要行只报 gap、不说「你指的那张不存在」,签字的人在审核页上根本看不见它。

两道闸,分工不同:

1. **`lib/editorial.py`,读取时。** 不认识的字段名、不认识的 `source`、
   少掉的 `n`、写成 `cn` 的中文键、上下界写反的 GPS 框 —— 全部当场退出,
   错误信息里带产品代码和它在文件里的位置,例如:

   ```
   work/WBCHET/editorial.json section_overrides.d06[0]: 不认识的图源 'stok'
   ```

2. **`bin/compose.py`,解析引用时。** 指向一个不存在的候选(block 名打错、
   序号超出),只有它知道 `candidates.json` / `commons.json` 里到底有什么:

   ```
   WBCHET section_overrides.d06: commons d06_typo#3 不在 commons.json 里
     —— 先跑 `python3 bin/fetch_commons.py WBCHET`
   ```

两种情况都有测试守着(`tests/test_editorial.py`)。

---

## 做一本新册子时,这个文件什么时候写

`commons_region_box` 和 `stock_region` 要**在抓候选之前**写好 —— 它们决定
搜什么、以及那一轮做不做 GPS 范围检查。缺文件不会让抓取失败(新产品跑到那一步
时它本来就还不存在),但两个脚本会把代价打印出来。其余字段是看过候选图之后
才写得出来的,顺序见 `docs/UPLOAD_RUNBOOK.md` 第 8 节。

**搬数据不等于把选片自动化。** `bin/review_page.py` 出的配图审核页仍然要人
看过才往下走。这个文件记录的是人已经做过的判断,不是替代那个判断。

---

## 重新生成 / 核对

这 17 个产品的文件是 `tools/migrate_editorial.py` 从迁移前的源码抽出来的,
脚本可重复执行 —— 它从 git 里取那一版 `bin/*.py` 再抽,所以任何人都能重跑
一遍和仓库里的比:

```bash
python3 tools/migrate_editorial.py --out /tmp/editorial
for d in /tmp/editorial/*/; do
  diff "$d/editorial.json" "work/$(basename "$d")/editorial.json"
done
```

`tools/verify_equivalence.py` 是配套的另一半:拿迁移前后的两版 `compose.py`
各跑一遍,逐字节比 plan。
