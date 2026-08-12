# 阶段一设计 — 文档进,官网产品出

目标:Planner 丢一份行程文件进来,产品以**草稿态**落到 Skybear 生产后台,内容和配图达到
`www.webuytravel.sg` 上已发布产品的水准。上架那一下永远留给人。

这份文档只写**实测得到的**结论。每条都标了怎么验的,推断和事实分开写。

---

## 1. 目标形态:一个成品产品页由什么组成

参照 [tours/112 Altay Wonders](https://www.webuytravel.sg/tours/112-10d9n-travel-with-marcus-chin-altay-wonders)
(2026-08-12 实地看的线上页面)。前台渲染出来的结构自上而下:

| 页面元素 | Skybear 字段 | 备注 |
|---|---|---|
| 顶部大图 | 轮播图 position 0 | 被裁成很宽的 hero 条,竖图在这里会废掉大半 |
| 标题 + `10 DAYS` + `FROM S$2,799 / PAX` | product_name / travel_days / wt_tour_price | 天数和价格来自团期,不是内容 |
| 轮播缩略图条 | Desktop / Mobile Display Image | **两套独立槽位**,不是一套 |
| About this group tour 下的要点列表 | `wt_travel_highlights` | 含餐食清单那几行 |
| 每日:标题 / 地点 / 餐食 | section_title / section_location / section_description | 地点是金色全大写那行 |
| 每日右侧一张大图 | `wt_travel_section_image` | |
| **每日下方的景点卡:标题 + 描述 + 3 张小图** | **Trip Item + Trip Photos** | ← 见下方缺口 |

### ⚠ 已知缺口:Trip Item

线上参考页里,每天正文的主体其实是**景点卡**(「Grand Bazaar」+ 一段描述 + 3 张配图),
不是 section description。而 skybear-uploader 明确跳过了这一层——它的 SKILL.md 写着
`Trip Item: SKIP (Phase 0 unresolved structure)`,Phase 3 也只查到「是 wt_travel_section
的子记录,具体表未确认」。

**所以照搬 skybear-uploader 传出来的产品,跟用户给的参考样例之间会差一层。**
这一层要么在阶段一补掉,要么明确降级(每天只有一张大图 + 餐食行),不能默认它不存在。

---

## 2. 输入:PDF 和 Word 不是同一种东西

这是拿真实样本试出来的,不是设计假设。

### PDF = 成品行程册(图多)

`WBCKWE - 9D8N GUIZHOU & CHONGQING WONDERS TOUR.pdf` 等三份:排版精美、英文、
内嵌真实景点照片。`lib/pdf_images.py` 的字节级 DCTDecode 抽取能直接取出来。

### Word = 地接社报价单(几乎没图)

`WBCKWE.doc`(2026-07-21):**中文**,发件方是「贵阳四季优美国际旅行社」,
内容是 D1~D9 逐日的景点 / 餐食 / 酒店 + 人数用车等报价要素。

实测(`textutil -convert html` + 字节扫描):

- 128 行正文,行程结构完整——**文本质量比 PDF 更细**(带酒店名、每餐菜系、含不含电瓶车)
- **0 个 JPEG,1 个 PNG**(应是抬头 logo)——**没有可用配图**
- 老 OLE `.doc` 格式,`python-docx` 读不了;macOS `textutil` 可以,本机没有 libreoffice

### 由此定下的两条分支

| | PDF 路径 | Word 路径 |
|---|---|---|
| 行程文本 | 从 PDF 读(英文,偏营销) | 从 doc 读(中文,偏执行细节) |
| 双语 | 缺中文,要补译 | 缺英文,要补译 |
| 配图 | ①文档自带图优先 | **文档里没有图,只能全靠②③** |

**结论:「优先用文档内的图片」这条规则对 PDF 成立,对 Word 天然不成立。**
Word 输入必须依赖后面两级图源,这也正是要接 `webuy-itinerary-creation` 找图能力的原因。

---

## 3. 配图三级优先

```
① 文档自带图      PDF 内嵌照片 / docx 的 word/media/     ← 最可信,但 Word 路径为空
② Webuy 自家图库   webuytravel.sg 已发布产品的 OSS 原图    ← 已授权、同风格、尺寸对
③ 外部图源        webuy-itinerary-creation 的找图能力      ← 覆盖前两级的空白
```

②的覆盖度极不均匀,这是实测数字(2026-08-06):贵州 + 重庆两个在售产品几乎盖满
WBCKWE 全部景点;Altay 盖住 WBCURC 的大部分新疆段;**山西没有任何在售产品,
WBCHET 从这一级拿到 0 张。**

③在没有 key 的时候只剩 Wikimedia Commons,而 Commons 是档案馆不是图库:
48 个候选只有 4 个能用(搜「可可托海」返回矿石标本,搜「乌鲁木齐」返回中国地图)。
接 `webuy-itinerary-creation` 的价值就在这里。

**不管哪一级来的图,主体判断一律靠看图,不靠图注。**
行程册的图注实测会错:WBCURC 那本 9 张图有 3 张图注写错景点(标着「铜仁大峡谷」
的其实是吐鲁番火焰山),因为新疆册子是拿贵州册子改的。

---

## 4. Skybear 生产表单的雷(2026-08-06 实测)

移植自 skybear-uploader `lib/selectors.yaml` 的 `phase_4_prod_findings`。
**这些是在生产 Create 表单上验的,跟编辑已有草稿的行为不一样。**

| 雷 | 后果 |
|---|---|
| **新建表单 `publishStatus` 默认 = true,复选框已勾** | 直接点保存 = **当场发布到线上**。「不要勾」这条规则在新建表单上是空话,必须主动取消勾选并回读确认 |
| `travelMgmt/editTravel` 无团期时 500 `tourId Cannot be empty` | wt_travel 不能先于 wt_tour 存在 → **必须先开团期** |
| 双语字段 key 是 `zh` 不是 `cn`(产品名例外,用 `{enName, chName}`) | 写 `.cn` 静默失效,保存时才报验证错误 |
| 产品名不接受 `&` | 三份册子的标题全都带 `&`,要换成 `and` |
| 四个按钮都叫 Save/Confirm,三个在隐藏弹窗里 | 点错会触发别的弹窗的验证 |
| 图片槽位接受页面内合成的 File | 可以喂本地生成的裁剪图,不用文件选择器 |

---

## 5. 阻塞:先有团期才能有产品

`tourId Cannot be empty` 不是可以绕开的校验,是数据模型约束。要开出团期,需要
Planner 提供 PDF 里没有的信息:

**必填**:出发日期、航司代码、去程航班(航班号/起降时间/机场)、返程航班、
领队姓名、库存、Twin 价、机场税
**可选**(有默认值):返程日期(按天数推)、单房差(400)、儿童加/不加床价差(-40/-100)、婴儿价(0)

三个产品各要一份。**这是阶段一唯一真正的外部依赖。**

---

## 6. 与 AI Planner 的关系(阶段二的接点)

AI Planner 的 `module/content` 领域已经做过高度重叠的事:Issue #34
「成品行程 PDF 导入 → 结构化行程+图片 → QA → Skybear 上传闭环」用的样本
**正是 WBCKWE**,已经跑到 test01 并验证通过(travelId=391)。

两边的实际分工现状:

- AI Planner:test01 那一腿已验证;**生产那一腿(Issue #85)建卡后 0 条评论,从没跑过**
- 本项目:直接面向生产,先把三个产品送上去

阶段二的对接点因此很清楚:**本项目往生产写,写完把「哪个行程已上传」回告 AI Planner**,
补上 #85 一直没走的那一步,而不是各自维护一套行程数据。
