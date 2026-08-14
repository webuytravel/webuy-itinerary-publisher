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

### Trip Item:缺口已补(2026-08-13)

线上参考页里,每天正文的主体其实是**景点卡**(「Grand Bazaar」+ 一段描述 + 3 张配图),
不是 section description。skybear-uploader 明确跳过了这一层(`Trip Item: SKIP
(Phase 0 unresolved structure)`),照搬它的产品会比参考样例少一层。

**这一层现在填上了。** 生产表单里的结构是:

```
.itinerary-container .el-collapse-item          ← 一天
  .section-content .form-group                  Section Name/Title/Location/
                                                Description/Photos
  .trip-items .trip-item .trip-content           Trip Type/Title/Description/
                                                Photos,每个景点一份
```

必填项实测(读 `is-required`,不是猜):Tour Type、Product Name、Highlight、
List Thumbneil、Mobile Display Image、Desktop Display Image、Itinerary、
Section Name、Section Title、**Trip Type**、**Trip Title**。其余可空。

两处要注意:

- **Trip Type 是必填的 el-select**,而行程文件里没有这个字段——册子写的是看什么,
  不是怎么归类。取值只有七个,`bin/make_payload.py` 按标题开头判断:开头是移动
  (`Coach to` / `Homeward` / `Transfer`)算 Transportation,其余算 Attractions。
  只看开头三个词是有意的——「Optional Desert Activities and Return to Ordos」
  是一个沙漠下午,不是一段交通,归错会让它在页面上消失。
- **某天可能一个景点都没有**(WBCHET 第 9 天只有回程航班)。表单每个 section
  自带一条 trip item 且必填,所以这种天要**删掉**那条空行,而不是编一条内容填进去。
  删除要走一个确认弹窗,而且**折叠状态下删不掉**——移除动画停在 `el-list-leave`
  不结束,DOM 里那条还在。先展开 section 再删。

### 1.1 Trip Photos 才是自家产品挂图的地方,我们挂反了(2026-08-13 现查)

`Trip Item` 这一层填上了,但 **`Trip Photos` 一张都没传过**——五个产品 126 个景点
条目全是空的(DESIGN 第 7 节把它记成「非必填,当前流程留空」)。当时的判断是
「当天配图挂在 Section Photos 就够了」。

查了三个已发布的内蒙产品(见 3.1),这个判断是反的:

| | Section Photos | Trip Photos |
|---|---|---|
| 75 / 213 / 306(线上已发布) | **全部为 0** | 0 / 48 / 22 |
| 408–412(我们做的) | 9–12 张 | **全部为 0** |

**三个线上产品一张 section 图都没有,图全挂在景点条目上。** 也就是说我们和
自家在售产品的做法**正好相反**。参考页 `tours/112` 上「每天正文的主体是景点卡 +
3 张小图」这个观察(第 1 节)说的就是 Trip Photos 这一层,只是当时没意识到
Section Photos 在自家产品里其实是空的。

这不是「哪个对」的问题——两层都是有效槽位,前台都渲染。但如果目标是「和在售产品
一个水准」,**Trip Photos 是主战场,不是可选项**。逐日一张 section 图更像是我们
自己发明的折中。

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
③ 外部图源        webuy-itinerary-mcp 的 fetch_photo      ← 覆盖前两级的空白
④ AI 生成        webuy-itinerary-mcp 的 generate_image   ← 长尾兜底
```

### ③④ 怎么接:直接 HTTP 调线上服务,不复制代码

`webuy-itinerary-creation` 已经作为 MCP 服务部署在
`https://webuy-itinerary-mcp.onrender.com/mcp`,`/health` 实测三个图源 key
(Gemini / Unsplash / Pexels)**都已在服务端配好**——本项目一个 key 都不用配。

两个能用的工具:

- **`fetch_photo(subject, region, count, quick=True)`** — 查 Unsplash + Pexels,
  几秒返回候选 URL + 440px 缩略图。
  实测拿之前的两个失败案例重跑:「可可托海」返回 4 张真实新疆风光(不再是矿石标本),
  「乌鲁木齐」6 张里有 1 张精确命中北园春市场——**比 Commons-only 强一个量级**,
  但仍有 1 张跑到了土库曼斯坦。
- **`generate_image(prompt, aspect_ratio)`** — Gemini 文生图。
  **这是 stock 永远覆盖不到的长尾的解法**,也是 WBCHET 山西段的现实出路。

三个坑,接之前先规划:

1. 🚨 **`/mcp` 目前没有鉴权**——`WEBUY_MCP_TOKEN` 没设在 Render 上,不带任何
   Authorization 头就能完成 MCP 握手。**公网任何人都能消耗这套 Gemini/Unsplash 额度。**
   接入前应先让他们设上并给我们 token。这是个独立于本项目的安全问题。
2. `quick=False`(带 Vision 校验 + 美学排序)实测单个主题跑 **6 分钟以上**,
   服务自己的文档也警告不要整本用——**不能放进逐日循环**。
   所以质量把关只能由**我们这边看缩略图**来做。
3. Render 重启会清空 `/asset/` 和 `/download/`,拿到 URL 要立刻下载落地。

### 这个仓库帮不上的两件事

- **它完全不抽取 docx 内嵌图片**(`flatten_docx` 只处理 `p` 和 `tbl`,drawing 直接丢)。
  「优先用文档自带的图」这条核心需求得自己写。
- **它明确拒绝老 `.doc`**(检查 zip magic,不是 PK 就报错让人另存为 .docx)。
  本项目的样本恰好就是 `.doc`,得自己处理(`textutil` 实测可行)。

②的覆盖度极不均匀,这是实测数字(2026-08-06):贵州 + 重庆两个在售产品几乎盖满
WBCKWE 全部景点;Altay 盖住 WBCURC 的大部分新疆段;**山西没有任何在售产品,
WBCHET 从这一级拿到 0 张。**

### 3.1 ②这一级一直在错的地方找:公开站只是 Skybear 的一个子集

**上面那句「WBCHET 从这一级拿到 0 张」有一半是错的,2026-08-13 业务同事质疑后现查
才发现。** 错的不是数字(它确实拿到 0 张),是**结论**——不是「内蒙没有在售产品」,
是**我们根本没去看有没有**。

`lib/catalogue_source.py` 把这一级定义成「`webuytravel.sg` 已发布产品的 OSS 原图」,
`CHINA_INDEX` 指向 `webuytravel.sg/china-tours`。但那个索引页**滚到底只列 12 个中国团**,
而 Skybear 里 `travelStatus=1` 的产品有 **237 个**。公开站是 Skybear 的一个子集,
不是它的镜像。

按产品名扫这 237 个,内蒙古有三个已发布产品,**一个都不在公开站索引上**,
用产品名推出来的 slug 去 `tours/<id>-<slug>` 也全部 404:

| id | 产品 | 图片分布 |
|---|---|---|
| 75 | 10D8N 沙漠与草原双重体验 呼和浩特·响沙湾·希拉穆仁 | 7 横版轮播 + 1 缩略图,**section 0、trip 0** |
| 213 | 7D6N WINTER ROMANCE 内蒙火山·沙漠·草原 | 1 轮播 + **48 张 Trip Photos**,section 0 |
| 306 | 9D8N JOURNEY TO INNER MONGOLIA 房车穿越草原 | 10 轮播 + **22 张 Trip Photos** + 路线图,section 0 |

合计约 **88 张**已授权的内蒙实拍,而且 213/306 的图是**逐个景点挂的**,标签就是
Trip Title,比公开站的 `alt` 还准。和 WBCHET 的重合度很高(方括号是该条目的图片数):

```
Dazhao Temple[4] · Saishang Old Street[4] · Xilamuren Grassland[4]
Blue Khadag Toast Ceremony & Welcome Wine[2] · Mongolian Costume Photo Shoot[2]
Camel Ride & Desert Sightseeing Train[3] · Camel Roller Coaster & Desert ATV[4]
Desert Bonfire Party & Fireworks[4] · Ordos Wedding Performance[4]
Inner Mongolia Museum[4] · Wang Zhaojun Museum[4]
```

正好覆盖 WBCHET 的 D2(草原 / 迎宾仪式 / 蒙古族服饰)、D3(响沙湾沙漠活动)、
D7(呼和浩特大召寺)。**WBCHET 那 18 张 stock 里有相当一部分本来不必去外面找。**

**山西和宁夏是真的没有**:237 个已发布产品里,按 五台/平遥/云冈/悬空/应县/大同/太原
和 沙坡头/中卫/腾格里/贺兰/水洞沟/西夏/银川 扫,零命中。

#### 两条要改的

1. **②这一级的产品清单要从 Skybear 取,不是从公开站爬。** 鉴权头在后台任意页面
   patch 一下 `XMLHttpRequest.prototype.setRequestHeader` 就能拿到,
   `travelMgmt/queryListPage` 一次就能列全 300+ 条(用法见 UPLOAD_RUNBOOK 1.2)。
   图片本身仍然从 `prod-webuysg.oss.webuy.ren/travel-video` 直接下载,那个 bucket 是
   开放的,这部分不用改。
2. **`tours/112` 现在是 `travelStatus=0`(Unpublished)。** 它的公开页面还能打开、
   本文多处拿它当「线上在售参考产品」——**那句话现在不成立了**,它已经下架,
   只是静态页还在。作为「自家出品的版式参考」仍然有效,作为「在售」不再有效。

> 教训和第 5 节是同一条,只是换了个对象:那次是团期,这次是图库。
> **凡是「线上有没有 X」这种判断,一律现查,而且要查到权威的那个源。**

③在没有 key 的时候只剩 Wikimedia Commons,而 Commons 是档案馆不是图库:
48 个候选只有 4 个能用(搜「可可托海」返回矿石标本,搜「乌鲁木齐」返回中国地图)。
接 `webuy-itinerary-creation` 的价值就在这里。

### 3.2 ③这一级写下来的链路和实际跑的链路不是同一条

2026-08-13 逐条核对生产上那 45 张外部图,发现文档描述的图源顺序**一条都没走**。

`lib/photo_source.py` 的开头写的优先级是:

> **Shutterstock(Webuy 已购图库)→ Unsplash → Pexels → Wikimedia Commons**,
> 其中 Commons 结果带坐标,**超出 `max_distance_km` 的直接丢弃**。

实际跑的是 `lib/mcp_photos.py` → 线上 MCP 的 `fetch_photo`,而那个服务
`/health` 报的 key 只有 **Gemini / Unsplash / Pexels**。落到生产的 45 张:

| 实际来源 | 张数 | 域名 |
|---|---:|---|
| Pexels | 33 | `images.pexels.com` |
| Unsplash | 11 | `images.unsplash.com` |
| 手工放进 `OVERRIDES` 的本地文件 | 1 | (无 URL) |

**两件本该起作用的东西一次都没起作用:**

1. **Shutterstock 这一级从来没跑过。** `SHUTTERSTOCK_TOKEN` 本地没设,MCP 服务端
   也没配。它在文档里排第一、理由是「付费且精选,冷门中国景点上质量占优」——
   而它恰恰是我们没在用的那一级。`_shutterstock()` 里 `if not token: return []`,
   **没有 token 就静默返回空**,和 6.9 那批 bug 同一种失败方式。
2. **Commons 的 GPS 闸门也从来没跑过。** 它只存在于 `photo_source.py` 里,而
   `photo_source` 在主流程上没有被调用。**这是整条链上唯一一个能机械判定
   「地方不对」的检查**,换成 MCP 之后就没有了——6.7 那一长串「主体对、地方不对」
   之所以只能靠人眼逐张看,原因就在这里。Pexels/Unsplash 的返回不带坐标,
   想恢复这个闸门也没有数据可用。

### 3.3 生产上有一张图,来源没有记录,许可证标签是猜的

45 张里那张没有 URL 的,是 WBCURC(409)第 3 天的可可托海额尔齐斯大峡谷。它是
`bin/compose.py` 的 `OVERRIDES` 里一条 `("file", "work/WBCURC/cand/d03_keketuohai_canyon.jpg", …)`,
而 `file` 这个分支是这么写的:

```python
elif kind == "file":
    plan.placements.append(Placement(
        ..., credit="Wikimedia Commons", license="CC BY-SA 4.0", ...))
```

**credit 和 license 是硬编码的**,不是查出来的——任何本地文件从这个分支进来,
都会被盖上「Wikimedia Commons / CC BY-SA 4.0」这个章,不管它实际是什么。
`work/WBCURC/candidates.json` 里 `d03_keketuohai` 那组只有 pexels 条目,文件名
也对不上,所以**这张图的真实出处在仓库里没有任何记录**。

看文件本身能拿到的(EXIF):HUAWEI NOH-AN00、Snapseed 2.0 修过、2021-06-26 拍,
**GPS 47.298 / 89.971 —— 距可可托海额尔齐斯大峡谷 21 km**。所以**地方是对的**,
而且它是全部 103 张里唯一一张能用硬证据(而不是靠看)确认地点的。

但**如果它真是 CC BY-SA 4.0,那就欠着署名和相同方式共享**,而 Skybear 产品页上
没有任何地方放署名。这需要产品/法务定,不是这里能决定的:要么找回原始出处补上
署名,要么换掉这张图。

**代码这边该改的是**:`file` 分支不能再硬编码 credit/license,应当由 `OVERRIDES`
显式提供,提供不了就拒绝——这正是 6.9 那条判断标准的又一次应用。

### 3.35 被关掉的那一级恰好是最擅长中国景点的:Wikimedia Commons

2026-08-13 业务同事提出「外部两个图源找不到的太多,还有没有别的源」。把 Commons
重新打开试了一遍,结论和 3.2 之前的判断**相反**。

拿今天 Pexels/Unsplash 全军覆没的主体逐个打(`lib/photo_source._commons`,免 key):

| 主体 | Pexels/Unsplash | Commons |
|---|---|---|
| 西夏陵 | 6 张里 3 张兵马俑、1 张大雁塔 | **5 张真的西夏陵**(贺兰山下夯土陵台),全部带 GPS、2000px、CC BY-SA 4.0 |
| 乌兰哈达火山 | 没搜过 | **3 张**火山口航拍,全部带 GPS,同一作者 |
| 开平碉楼 | 返回城墙、灯塔、城门,一张碉楼都没有 | **6 张**,4 张带 GPS |
| 悬空寺 | — | 6 张,全部带 GPS |
| 应县木塔 / 云冈石窟 / 佛山祖庙 | — | 各 6 张,2000px |
| 览山公园 / 贺兰山岩画 / 忻州古城 | 全废 | **0 张**(Commons 也没有) |

**为什么会反过来:** Pexels/Unsplash 是按「好看」组织的通用图池,3.1 那个「换个地名
再搜一次,结果重叠」的检验说明它们**不解析地名**;Commons 是**按主体归档的资料库**,
条目名就是地名,所以在「有名有姓的中国文物古迹」这一类上正好是它的主场。

**之前为什么把它判死了。** `photo_source.py` 自己的注释里写着答案:Commons 全文
检索接近 AND,**每多一个词就少一批结果**——实测 `Hongyadong` 有 6 条,
`Chongqing Hongyadong night Guizhou China` 是 0 条。08-06 那次「48 个候选只有 4 个
能用」应该是带区域词搜的。**正确用法是拿规范英文名裸搜**,别加区域词。

#### 覆盖率:56% → 73%

把五个产品全部 126 个景点条目跑一遍(`work/_commons_coverage.json`):

| 产品 | 景点条目 | 现有图能覆盖 | Commons 能覆盖 | **并集** | 仍缺 |
|---|---:|---:|---:|---:|---:|
| WBCKWE | 21 | 13 | 13 | **19** | 2 |
| WBCURC | 35 | 14 | 16 | **21** | 14 |
| WBCHET | 31 | 17 | 12 | **22** | 9 |
| WBINC9 | 19 | 16 | 3 | **17** | 2 |
| WBSZX1 | 20 | 11 | 6 | **14** | 6 |
| **合计** | **126** | 71(56%) | 50(39%) | **93(73%)** | **33** |

而且 Commons 这一级顺带解决了 3.2 和 3.3 的两个问题:**它带 GPS**(唯一能机械判定
「地方不对」的数据),**而且 `_commons()` 已经把 `LicenseShortName` 和 `Artist`
读出来了**——出处和作者是有记录的,不像 3.3 那张只能靠 EXIF 反推。

#### 署名:业务已确认可以直接用(2026-08-14)

抽样 33 个候选,许可证以 CC BY-SA 3.0/4.0、CC BY 2.0/3.0 为主,**CC0 只有 2 个**,
即**九成以上要署名**,而 Skybear 产品页没有署名字段。这一条 2026-08-14 由业务确认
**A2(Commons)和 A3(册子图)可以直接用**,不再作为开这一级的前置条件。

**但事实本身不变,记在这里给以后的人:** `_commons()` 已经把 `LicenseShortName` 和
`Artist` 读出来了,**落进 `plan.json` 的每一张都带着这两项**。所以哪天要补署名,
数据是齐的——不用回头重查。这也正是 3.3 那张图做不到的事(它的出处只能靠 EXIF 反推)。
**不要在管线里把这两个字段丢掉。**

### 3.4 版权不是主要风险,「不是那个地方」才是

Unsplash 和 Pexels 的许可都允许免费商用、不强制署名,所以那 44 张在版权上是干净的。
真正的风险在另一头:**卖的是这条线路,配的却是别处的照片。** 6.7 记的那一串
(搜西夏陵返回兵马俑、搜驼车返回南亚单峰驼、搜大巴扎返回希瓦古城)如果漏一张上线,
问题不是侵权,是**广告与实际不符**。这也是为什么这一级的图必须逐张人签字,
以及为什么 3.1 里那 88 张自家内蒙实拍值钱——它们的地点是 CMS 记下来的,不用猜。

### 3.5 图源全盘点(2026-08-13)

按「能不能今天就用」排,不按理论优先级排。

| | 图源 | 状态 | 覆盖 | 授权 | 地点可验证 |
|---|---|---|---|---|---|
| **A0** | **数据中台媒体素材库**(`webuy-data-platform` Media Asset API) | 没接过,接口已就绪 | 全公司素材,按 `subject_entities` 检索 | **字段级已治理** | ✅ `subject_entities` |
| A1 | **Skybear 全量自家图库** | 代码只爬公开站(12 个),要改成走 Skybear(237 个) | 内蒙一地就 88 张 | 已授权 | ✅ CMS 标注 |
| A2 | **Wikimedia Commons** | 已实现,主流程没调用 | 126 个条目覆盖 39% | ⚠️ 九成要署名 | ✅ GPS |
| A3 | **册子内嵌照片** | 在用 | 每本 4–9 张 | 自家 | ❌ 图注会错 |
| B1 | **Pexels / Unsplash** | 在用(45 张全从这来) | 中国景点上很差 | 免费商用免署名 | ❌ 不解析地名 |
| B2 | **Shutterstock** | 代码有,没 token,静默返回空 | 未测 | 需逐张购买 | ❌ |
| B3 | **Gemini 生成图** | 服务端 key 已配,**一张没用过** | 无限 | 生成物 | ❌ 不是实拍 |
| C1 | **地接社** | 没接过 | 就是这条线路本身 | 需约定 | ✅ 他们踩过点 |
| C2 | **往期出团 / 领队照片** | 没接过 | 已成团的线路 | 自家 | ✅ |
| C3 | **中文商业图库**(视觉中国 / 图虫 / 站酷海洛 / 摄图网) | 没接过 | 中国景点最全 | 需采购 | ⚠️ 看标注 |
| C4 | **文旅局公开宣传素材** | 没接过 | 按省 | 需逐个确认 | ✅ |

**明确不能用的:** Google Places Photos(许可只允许在 Google 地图内展示)、
百度/搜狗图片搜索、携程/马蜂窝/小红书的 UGC——都没有商用授权。

**C1 是被忽略最久的一个。** 第 2 节记着 WBCKWE 的 Word 报价单来自「贵阳四季优美
国际旅行社」——**地接社手里有这条线路的真实照片**,而且他们有动力提供。这条不需要
写任何代码,是采购/商务动作。上面所有技术手段都在解决「怎么找到一张看起来像那个
地方的图」,而地接社给的是**那个地方本身**。

#### A0 数据中台媒体素材库:唯一一个版权和肖像都已经治理过的源

`webuy-data-platform` 的 Media Asset API(`/wb_data/api/media`,联调说明见产品侧
文档 `2026-07-08-media-asset-api.md`)是这份盘点里**唯一一个把「能不能用」做成
字段**的源。检索按 `subject` / `subject_entities`(景区/地标/城市级实体),而不是
靠全文相关性——正好治 3.1 那个「换个地名结果重叠」的毛病。

对本项目有用的几个字段:

| 字段 | 我们要拿它做什么 |
|---|---|
| `subject_entities` | 景点级实体,直接对 `photo_subject`;`subject` 参数支持中英别名归一化 |
| `copyright_source` | 只收 `owned` / `licensed`;`web` 一律不要 |
| `asset_cleanliness` | 只收 `clean`;`third_party_watermark` / `social_media_scrape` 排除 |
| `scene_type` | 要 `scenery` / `product_shot`;**必须 `exclude_scene_type=["ad_creative"]`** |
| `overlay_signals` | `has_text` / `has_price` / `has_cta` 命中的不要——产品页上不能有别处的烫字 |
| `people_signals` + `portrait_authorization_status` | 有可识别人脸而肖像未授权的不要 |
| `orientation` | `landscape` 给 section,`portrait` 给竖版轮播,省掉一次重裁 |

两条要注意:

1. **`customer_send_eligible` 不是我们的开关。** 文档写明它是「对客 1:1 会话自动发送」
   的派生值,**投放和内部使用不得拿它当总开关**。产品页配图属于对外投放,要自己按
   `copyright_source` + `asset_cleanliness` + `scene_type` + `overlay_signals` 组合判断,
   而不是图省事读那一个布尔。
2. **`r2_signed_url` 是临时的**,TTL 默认 120 分钟、上限 240 分钟。和 3 节记的
   Render `/asset/` 一样:**拿到就下载落地,不要存 URL**。取内部用途的 URL 要
   `usage_context=internal`,且 token 需要 `media-assets:internal-access-url` scope。

**这是公开仓库,API key 只能走环境变量 `WEBUY_MEDIA_API_KEY`,不许写进代码或文档。**

**不管哪一级来的图,主体判断一律靠看图,不靠图注。**
行程册的图注实测会错:WBCURC 那本 9 张图有 3 张图注写错景点(标着「铜仁大峡谷」
的其实是吐鲁番火焰山),因为新疆册子是拿贵州册子改的。

---

## 3.6 册子里的图为什么不能全用(2026-08-14 逐张核对)

五本册子里 `lib/pdf_images.py` 一共抽出 **61 张栅格,只有 23 张进了配图**。
业务同事问剩下的 38 张怎么了。逐张归类:

| | 张数 | 是什么 | 判断 |
|---|---:|---|---|
| ① 闸门拒绝 · furniture | 15 | 小于 300px 短边:logo、图标、分隔条 | **不是照片,拒绝对** |
| ① 闸门拒绝 · banner | 6 | 长宽比 > 3.0 的页眉/页脚条 | **不是照片,拒绝对** |
| ② 路线图 | 5 | 册子自己的行程示意图 | **没浪费**,进了 route_map 槽 |
| ③ 封面整版 | 5 | 封面营销版式 | **拒绝对**,见下 |
| ④ 真照片但太小 | 7 | 裁到 4:3 只有 420–610px | **只有这一档可惜** |
| ✅ 已用 | 23 | | |

**③ 封面整版为什么不能用。** 打开看过:是烫字标题(「9天8晚 黔渝秘境之旅」)+ 价格
徽章 +「NO SHOPPING」印章 + WeBuy Travel logo + 一排小图拼贴的整版营销稿。它是
**版式**不是照片,放进景点位就是把另一份广告贴到产品页上。`_is_cover_poster` 的
判据是「该页文字 < 50 字符 且 图占版面 ≥ 80%」——纯图版面才会命中,不会误伤正文配图。

### 3.6.1 那 7 张是真照片,卡住它们的阈值来自一个没量过的假设

看过的五张:苗族歌舞表演、小七孔翠水撑船、千户苗寨吊脚楼、新疆民族歌舞、
卡拉麦里公路上横穿的鹅喉羚。**全是这条线路上的真实照片**,只因为尺寸被丢。

阈值是 `MIN_PDF_CROP_WIDTH = 632`,而它是算出来的:

```
SECTION.width / SECTION.max_upscale = 1200 / 1.90 = 632
```

也就是说,**册子照片的生死线是由 section 槽 1200px 的目标定的**。那 1200 从哪来的?
没有量过。

**2026-08-14 在线上参考产品 `tours/112` 上量了**(视口 1291×707):

| 页面元素 | 实际渲染尺寸 | 张数 |
|---|---|---|
| 顶部 hero 条 | 1283×460 | 1 |
| **每日 section 图** | **220×165** | 9 |
| **景点卡小图(Trip Photos)** | **89×89** | **68** |

**section 图在页面上只有 220px 宽,而我们按 1200px 供。**

但不能就此把阈值一砍了事——**那些小图是可以点开的**:`cursor: zoom-in`,点击弹出
灯箱。实测灯箱里那张渲染 **535×643**,源文件 `1080×1297`。

所以真正的下限是灯箱,不是缩略图。按 535–750px 的灯箱渲染(不同视口)重新看那 7 张:

| 裁后宽度 | 灯箱里的表现 |
|---|---|
| 610 / 590 px | 基本 1:1,**可用** |
| 513 / 492 px | 略放大,**可用** |
| 446 / 420 px | 1.3–1.8×,**边缘,retina 大屏上会看出软** |

**结论:632 这条线对 section 槽是合理的(它确实按 1200 供),但拿它当册子照片的
总闸门是过严的**——尤其对 Trip Photos 这种 89px 缩略图 + 535px 灯箱的位置。
自家图库的在售图也只是「1080-class 长边」(见 `catalogue_source.py` 开头),
1200 已经高于自家标准。

**该做的是给 Trip Photos 单开一个 SlotSpec**,目标按灯箱量出来的尺寸定,
而不是继续复用 section 的 1200。那样这 7 张里至少 5 张能直接回来。
在那之前,**不要只是把 632 调小**——那会让 section 槽也跟着降质,而 section
是唯一在页面上以大图出现过的日程图。

---

## 4. Skybear 生产表单的雷(2026-08-06 实测)

移植自 skybear-uploader `lib/selectors.yaml` 的 `phase_4_prod_findings`。
**这些是在生产 Create 表单上验的,跟编辑已有草稿的行为不一样。**

| 雷 | 后果 |
|---|---|
| **`publishStatus` 默认值不可预设** | 08-06 记录是默认已勾;08-13 三次新建实测都是**未勾**(选完 Tour Type 后重新初始化)。两种都出现过,所以规则不是「记住默认值」而是**每次保存前回读 + 截图确认**。勾着保存 = 当场发布到线上 |
| `travelMgmt/editTravel` 无团期时 500 `tourId Cannot be empty` | wt_travel 不能先于 wt_tour 存在 → **必须先开团期** |
| 双语字段 key 是 `zh` 不是 `cn`(产品名例外,用 `{enName, chName}`) | 写 `.cn` 静默失效,保存时才报验证错误 |
| 产品名不接受 `&` | 三份册子的标题全都带 `&`,要换成 `and`。选中 Tour Type 会**自动把产品名填成带 `&` 的册子标题**,必须覆盖 |
| 四个按钮都叫 Save/Confirm,三个在隐藏弹窗里 | 实测点到隐藏的那个:**没有任何反应,也没有报错**,看起来像保存卡住。按 `offsetParent !== null` 过滤出可见的那个再点 |
| **选中 Tour Type 会清空已上传的图片** | 顺序只能是「先选类型,最后挂图」。08-13 实测:选类型前传好的 List Thumbneil 当场没了 |
| 选中 Tour Type 会自动加载团期并**全部勾上** | 不用手动勾。实际团期数与 08-12 的记录对不上(见下),以页面为准 |
| 图片槽位接受页面内合成的 File | 但**字节不能用 fetch 从本地 http 服务器取**,见第 7 节 |

---

## 5. 团期:已经不再是阻塞(2026-08-12 复核)

`tourId Cannot be empty` 是真实的数据模型约束——wt_travel 不能先于 wt_tour 存在。
但**触发它的前提已经消失了**。

08-06 记录这条时,三个 TourType 都是零团期。08-12 在生产 Package List 上逐个查:

| 产品 | 团期 | 航司 | 期间 |
|---|---|---|---|
| WBCKWE | 8 个,如 `12WBCKWE24/26CZ` `09WBCKWE07/26CZ` | CZ | 2026 年 09–12 月 |
| WBCURC | 7 个,如 `10WBCURC12/27OD` `08WBCURC28/27OD` | OD | 2027 年 08–10 月 |
| WBCHET | 8 个,如 `10WBCHET14/27OD` `05WBCHET13/27OD` | OD | 2027 年 05–10 月 |

**团期是产品组在这六天里自己开好的。出发日期、航司这些原本要问 Planner 的信息,
现在直接从 Skybear 读就有——不用再问。**

反过来,Package Content Mgmt 里按关键词查,三个产品**都还没有 wt_travel**
(GUIZHOU 7 条无 WBCKWE、XINJIANG 5 条无 WBCURC、SHANXI 0 条)。
所以三个都走 NEW 模式,要新建展示产品——也就都会碰到第 4 节那个默认勾选的发布框。

> 教训:这条阻塞在上一轮被原样转述了一次而没有复核。**生产状态一律现查。**

---

## 6. 生产上传实录(2026-08-13,三个产品都已落库)

| 产品 | Product Id | 状态 | 团期 |
|---|---|---|---|
| WBCKWE 9D8N 贵州重庆 | **408** | Unpublished | 20 个 CZ,2026-09 → 2027-06 |
| WBCURC 13D11N 北疆包机 | **409** | Unpublished | 14 个 OD,2027-05 → 2027-10 |
| WBCHET 9D7N 山西内蒙 | **410** | Unpublished | 8 个 OD,2027-05 → 2027-10 |
| WBINC9 9D6N 宁夏沙漠黄河 | **411** | Unpublished | 12 个,2027-04-03 → 2027-10-16 |
| WBSZX1 7D6N 粤味八城 | **412** | Unpublished | 18 个 CZ,2026-09-23 → 2027-06-23 |

团期数与 08-12 的记录(8 / 7 / 8)对不上两项——WBCKWE 实际 20 个、WBCURC 实际 14 个。
**生产状态一律现查**这条又验证了一次。

### 6.5 已发布的 wt_travel 是一个没被覆盖的分支

第二批四本册子里,**两个 type_code 已经有 wt_travel,而且是 `travelStatus=1`
Published**:WBJGX8 → id 348、WBOHE1 → id 122。

「有就是 EDIT 模式」这条规则是在三个产品都不存在时写的,它默认「已存在」= 草稿。
已发布的记录**没有草稿态中间状态**:在上面编辑就是直接改客户看到的页面,与
「只到草稿态」这条红线冲突。所以这不是一个可以自己决定的分支,**是停下来问人的
信号**。08-13 用户选择跳过这两个,先做干净的两个。

**这两本册子讲的是已经在线上卖的那两个行程,不是新产品。** 08-13 逐条比对:

| | 册子 | 线上 | 结论 |
|---|---|---|---|
| WBJGX8 | 8 天,衢州→望仙谷→葛仙村→婺源→建德→杭州→乌镇→上海 | `tours/348`,S$1,099,38 张图,正文含 Wangxian/望仙/Gexian/Wuyuan/Hangzhou/上饶/上海 | **同一行程,换了个营销名** |
| WBOHE1 | 11 天,海拉尔→满洲里→呼伦贝尔→根河→北极村→漠河→加格达奇→五大连池→齐齐哈尔→哈尔滨 | `tours/122`,S$1,799,92 张图,正文含 Manzhouli/Hulunbuir/Mohe/Arctic/Wudalianchi/Qiqihar/Harbin/Genhe | **同一行程** |

所以这两个真正的工作不是「新建产品」,而是**给已上线记录做内容刷新**——一件性质
完全不同、也危险得多的事。新建只会造出重复产品。

另外两条:

- **348 的产品名和册子标题完全不同**(线上「8D7N SEA-OF-CLOUDS VALLEY ·
  CLIFFSIDE ANCIENT VILLAGE · JIANGNAN ELEGANCE LUX ESCAPE」= 云海峡谷·悬崖古村·
  江南,册子「8D7N JIANGXI & JIANGNAN SCENIC JOURNEY」),而且该 type_code 下的
  25 个团期挂着**两种 tourName**。**册子标题不能当作线上产品的标识去比对**,
  要按 type_code 查。
- **「ARTIC」这个错拼只在文件名和 Skybear 的字段里**:册子正文 `Arctic` 出现 10 次、
  `ARTIC` 0 次;而 61 个团期的 tourName、已发布产品 122 的产品名都是 ARTIC,
  连 `tours/122` 线上页面本身也是标题 Artic、正文 Arctic 两种并存。所以用户选
  Arctic 不只是「改成正确英文」,而是**与册子正文和线上正文一致**;不一致的是标题。

### 6.1 图片怎么进 file input:loopback fetch 是死路

原方案是起 `python3 -m http.server` 服务仓库根目录,页面 `fetch('http://127.0.0.1:.../x.jpg')`
拿字节再用 `DataTransfer` 塞进 input。**这条不通**:从 https 页面 fetch 本地 http origin,
promise 既不 resolve 也不 reject,console 一条报错都没有——看起来像自己的代码写错了,
其实是混合内容拦截。「Chrome 对 loopback 豁免混合内容」这条对 `fetch` 不成立。

**能用的是浏览器扩展自己的文件通道**(`file_upload`,给 input 的 element ref + 本地路径),
它根本不经过页面的网络栈。一个限制:路径必须在**本次会话可读的目录**内,仓库主检出
不算,所以 `work/**/out*` 要先复制进当前工作目录(它们本来就在 `.gitignore` 里)。

### 6.2 批量操作要同步连点,不能 click-await-click

`Add Section` / `Add Trip Item` 每点一次,Vue 会重渲染整个行程区,而这个渲染的开销随
已有 section 数增长。写成「点一次 → await → 再点」的循环,13 天那个产品**跑了二十多分钟
还没填完**:每次 await 都让 Vue 完整重渲一遍,单次点击从 250ms 退化到几十秒。

Vue 是批处理的:**在一个同步块里连发 N 次 click,只产生一次重渲染。** 同一个 13 天表单
用这种写法 16 秒填完。代价是同步块前后拿到的元素全部作废——写进已 detach 的 input
会「成功」但什么也不改。所以顺序是:连点 → 等一次 → 重新查询 → 填字段。

### 6.3 Highlight 就是 6 条,这是版式不是限制

表单只有 6 组双语输入,没有加行控件。行程文件里是 15–22 条。
查线上同类产品 `webuytravel.sg/tours/115` 确认:**它也正好 6 条**,而且格式固定——
4 条头部景点/体验,再 2 条用 `·` 压缩的餐食风味。所以不是被表单截断,是要按这个版式重排。
三个产品的成品 6 条写在 `bin/make_payload.py` 的 `HOUSE_HIGHLIGHTS` 里,连同取舍理由。

### 6.4 stock 图源返回的是预览图,不是原图

`photo_source` 存下来的是搜索结果给的**展示尺寸**:Pexels `?w=940&h=650`、Unsplash `&w=1080`。
WBCHET 的轮播源图因此全是 940×627,横版要上采样 1.72×、竖版 2.30×,超出规格允许的 2.0。

两个 URL 都把尺寸写在 query 里,去掉/调大就能拿到同一张照片的原图。`bin/resharpen.py`
做这件事:WBCHET 全部 18 张从 940px 上采样变成从 3000–6240px 下采样(0.22–0.90×),
WBCKWE 第 1 天从 2.04×(超出 section 槽 1.90 的上限)变成 0.92×。**选片没有变,只是像素变了。**

### 6.5 Mobile Display Image 一直是空的

轮播是两个独立必填槽位,而 `bin/compose.py` 只产出过横版,`work/*/out_mobile/` 三个目录
一直是空的。`bin/mobile_crops.py` 补上:按 `image_spec.CAROUSEL_MOBILE`(1080×1440)
**从原始源图重裁**——不是把 4:3 成品再裁一刀,那样只剩 810×1080 的一条,照片选它的理由
基本都被切掉了。

---

### 6.6 缩略图 = 轮播首图,而跨槽去重把这个设计当成了事故

`fill_carousel` 的最后一步是把轮播首图**再挂一份**到 List Thumbneil——这是有意的,
线上产品也是这样。但 `dedupe(cross_slot=True)` 的 `slot_priority` 里 thumbnail 排在
carousel 前面,于是它保留缩略图、**删掉轮播 position 0**;轮播随后重新编号,原来的
第二张升为首图,尾部由图库剩图补上。

结果是产品少一张轮播,而且**列表缩略图和轮播首图不再是同一张**。08-13 实测:

| 产品 | tours 图库来源 | cross_slot | 轮播张数 | 缩略图实际是什么 |
|---|---|---|---|---|
| WBCKWE 408 | 有(115/108) | True | **7** | 「9D8N Discover The Natural Wonders…」= 兄弟产品**横幅图** |
| WBCURC 409 | 有(112) | True | **7** | 「10D9N Travel With Marcus Chin - Al…」= 横幅图 |
| WBCHET 410 | 无 | False | 8 | 鄂尔多斯草原,正常 |

WBCHET 躲过去只是因为山西没有在售同类产品、走的是 `cross_slot=False`。
修法是让 thumbnail↔carousel 这一对免检(`lib/image_plan.py`)。

**修好之后重跑,才看清它一直在掩盖什么:被删掉的那张首图本身就是横幅图。**
`catalogue_for` 返回的第 0 条是 tours 列表页的横幅图,alt 就是产品名——四个采过
的产品无一例外。它排在 pool 最前,所以既是轮播首图也是缩略图;去重把轮播那份
删了、留下缩略图那份,症状才表现为「缩略图是横幅图 + 少一张轮播」。所以这里其实
是两个叠在一起的缺陷,单修去重会让横幅图正大光明地当上首图,比原状更糟。

第三个缺陷同时暴露:**同一景点重复**。图库每个景点存两三张,pool 按目录序取:

| | 修之前(线上) | 现在 |
|---|---|---|
| WBCKWE | 横幅图 → 甲秀楼×2 → 花果园×2 → 黄果树×3 | 甲秀楼 花果园 黄果树 天星桥 马岭河 万峰林 八卦田 小七孔 |
| WBCURC | 横幅图 → 大巴扎×3 → S21×2 → 乌伦古湖×2 | 大巴扎 S21 乌伦古湖 五彩滩 喀纳斯湖 湖上游船 图瓦晚宴 禾木晨雾 |

`dedupe` 抓不到重复主体,因为它的同主体规则按 `(slot, position)` 分组,而每张轮播
图各占一个 position。**主体多样性只能在挑 pool 的地方决定**,不能指望去重兜底。

三处都修完后,408 / 409 已于 2026-08-13 重跑并重传了缩略图与轮播两组槽位;
section、路线图、行程文本一字未动(逐条比对确认),两个仍是 Unpublished。

### 6.7 stock 的失败模式是「主体对、地方不对」,不是「找不到」

08-13 下半场两个产品又各撞了一次,形态和之前完全一样:

- **WBINC9「驼车」**:6 张候选全部是**单峰驼 + 南亚服饰**(拉贾斯坦/信德),
  不是中国双峰驼。放大看驼峰数是最快的判据。
- **WBINC9「贺兰山岩画」**:#1 是一面没有可辨刻画的岩壁,#6 是一块**现代红漆题字**
  的景观石——都不是史前岩画。
- **WBINC9「西夏陵」**:6 张里 3 张兵马俑、1 张大雁塔、1 张龙门;另开一组
  「一百零八塔」又返回**大理三塔**。
- **WBSZX1「佛山祖庙」**:#1 是**广州中山纪念堂**;#5/#6 是岭南祠堂,但无法从画面
  区分祖庙和陈家祠——最后改用图库里 CMS 标注的黄飞鸿纪念馆。
- **WBSZX1「开平碉楼」**:返回城墙、灯塔、城门,一张碉楼都没有。

**能救回来的一次**是 WBINC9 的黄河石林:因为册子里有一张真的,拿它当基准去比对
stock 的形态(赭色层理石柱),才敢把 stock 那张放进轮播。
**有基准图时才有可能确认「同一类地貌」;没有基准就只能确认到类型和地域。**

#### 一个不用看图就能下判断的检验:换个地名,再搜一次

08-13 给 6.11 那四天补图时,48 张候选零命中,其中有两组直接把机制暴露了:

- 搜「Ordos Museum 鄂尔多斯博物馆」和搜「Ningxia Museum 宁夏博物馆」,
  **返回了同一栋白色流线型建筑**(前者 4 张、后者 3 张,同一批文件)。
- 搜「Ordos city 鄂尔多斯城市」和搜「Yinchuan city 银川城市」,
  **返回了同样的两张中国大城市天际线**。

也就是说这一级返回的是**泛化的「中国博物馆」「中国城市」图池,地名根本没有参与
检索**。这比逐张看图快得多:**同一个题材换一个地名再搜一次,如果结果有重叠,
这一级对这个主题就是没有分辨力的,不用再往下看了。**
(顺带,那两组里还混进了香港故宫文化博物馆、西安大雁塔和一张人像。)

### 6.8 排除法定主体,只能用一次,而且必须标出来

WBSZX1 第 4 页有三张照片、页脚有三条图注(赤坎古镇 / 三十三墟街 / 日月贝)。
其中两张凭画面直接确认(骑楼+钟楼 = 赤坎;贝壳形剧院 = 日月贝),第三张就只剩
一条图注可对应了。

这次采用了这个推断,但**它和 WBCURC 那次翻车是同一类推理**(那次是跨册子复制导致
图注整体错位)。区别在于这次三张图注同属一页、另外两张各自独立确认过。
写进 `pdf_subjects.json` 时把推断过程和残余风险都写在 `note` 里,审核页会显示,
**由人签字**。画面本身只能确认到「岭南老街石阶巷」。

### 6.9 静默降级是这一批 bug 的共同病根

08-13 这一轮修掉的四处问题,失败方式是同一种:**每一处都不报错**,流程照常走完、
退出码 0、摘要行照常打印,只有最终页面上少了点什么。

| 位置 | 静默的表现 | 要多久才会被发现 |
|---|---|---|
| `dedupe` 删掉轮播首图 | 轮播少一张,缩略图换成别的产品的横幅图 | 上线后看列表页 |
| `form_filler.js` 的 `ReferenceError` | 表单其实填好了,但报告丢失,看起来像失败 | 当场,但会误导人重填 |
| `resharpen` 不刷新 note | 审核页上「放大 0.35×」紧挨着「upscaled 2.04×」 | 签字的人自己糊涂 |
| 审核页把所有无图日都叫「中转日」 | 真正的配图缺口在闸门页上看不见 | 上线后看产品页 |
| `materialise` 遇到源文件缺失 | 那天没有图,`plan.json` 里只多一行 note | 上线后看产品页 |

最后一条最典型:`OVERRIDES` 里的路径从某个 agent session 的 scratchpad 改成仓库
相对路径之后,「路径写对了」和「文件在」被当成了同一件事——而 `work/**/cand/`
是 gitignore 的,换台机器克隆下来那张图并不存在,于是重跑会再次静默丢掉第 3 天。

所以 `materialise` 现在**在编码任何东西之前先检查全部源,缺一个就抛
`FileNotFoundError` 并把缺失的全部列出来**。在编码前检查还有一层意思:失败的运行
不会留下半个 `out/` 目录,让后面的步骤误以为是完整的。

判断标准写在这里,给以后加代码的人:**当一个失败的后果是「页面上少了东西」而不是
「程序不能继续」时,它必须响。** 只有当降级后的结果仍然是一个可以交付的东西时,
留 note 才是对的。

### 6.10 生产表单会卡死整个标签页

选中 Tour Type 那一下,08-13 实测把标签页的主线程钉死:点击调用 45s 超时,之后
所有脚本注入 5s 超时,**同一 MCP 标签组里的另一个标签页也一起注入失败**。
hash 导航进不去(主线程不转就处理不了),带 query 强制整页重载也没用。

**唯一有效的恢复是开新标签页。** 表单在 Save 之前不写库,所以重来只是重做填写。
这也是「填写阶段中断是安全的」这条的实际用处——它不是理论上的安慰,是恢复手段。

### 6.11 有些天没有配图,而且没有任何地方说过(2026-08-13 业务同事发现)

业务同事看 410 的编辑页,反馈「每一天的介绍里只有 3 天有照片」。现查 410 的组件
模型(不是数 DOM,见 6.1):

```
D1 sec=0 | D2 sec=1 | D3 sec=1 | D4 sec=1 | D5 sec=2 | D6 sec=2 | D7 sec=1 | D8 sec=1 | D9 sec=0
```

**实际是 9 天里 7 天有图**,不是 3 天。差额的来源是编辑页**默认只展开 Section 1**,
而 Section 1 恰好是没有配图的那天——要逐天点开才看得见,不点开就只看到一个空的
抵达日。这条本身要写进手册(见 UPLOAD_RUNBOOK 6.2)。

**但他的结论是对的:D1 本来就该有图,而它是静默留空的。**

#### 线上在售产品的标准

`tours/112 Altay Wonders` 10 天(2026-08-13 看的线上页面):**第 1 天
「Singapore ✈ Urumqi」有配图**(抵达当天逛大巴扎),**只有最后一天
「Urumqi ✈ Singapore」没有**。所以规则不是「中转日不用配图」,而是:

> **除了纯回程那一天,每天都该有配图。抵达日有落地活动,它算正常的一天。**

#### 静默是怎么发生的:两个缺陷叠在一起

一、`bin/compose.py` 的 `subjects` 只从 `trip_items[].photo_subject` 来:

```python
subjects = [t["photo_subject"] for t in section.get("trip_items", []) if t.get("photo_subject")]
...
if placed == 0 and subjects:          # ← 这个 and
    plan.gaps.append(Gap(...))
```

WBCHET D1 有两个景点条目——`Depart for Ordos via Kuala Lumpur` 和
`Arrival and Hotel Check-In`——**两个都没写 photo_subject**。于是 `subjects` 是空的,
`and subjects` 短路,**既不配图也不记 gap**。`section["location"]` 里明明有 `Ordos`,
但 compose 从来不看它。(讽刺的是 `lib/image_plan.py` 的 `DaySection.search_subjects`
写了这个兜底 `landmarks or [location_en]`——但那是死代码,`DaySection` 全仓库没有
任何地方构造过。两份实现,活着的那份把兜底丢了。)

二、`bin/review_page.py` 把无配图日分两桶,然后**只渲染其中一桶**:

```python
transit  = [d for d in missing if not has_items.get(d)]      # 0 个景点条目 → 正常
unfilled = [d for d in missing if     has_items.get(d)]      # 有景点却没图 → 异常
... for d in unfilled if d in gaps                            # ← 没有 gap 记录就不渲染
```

D1 有 2 个景点条目 → 落进 `unfilled` → 但 compose 没给它记 gap → `if d in gaps`
把它滤掉。**它既不在「纯中转日」那行,也不在「有景点却没配图」那行,在签字页上
完全不存在。** 人工闸门看不见的东西,人工闸门拦不住。

第三处助攻:compose 的摘要行打的是 `sections=9 over 7 days`。9 天的产品少了 2 天,
这行字里读不出来——它读起来像在报进度,不像在报缺口。

#### 五个产品的实际情况

按新逻辑跑一遍 `section_gap`,之前静默的天全部现形:

| 产品 | 静默留空的天 | 该不该有图 |
|---|---|---|
| WBCKWE 408 | D9 Singapore(Homeward Bound) | 纯回程,可以空 |
| WBCURC 409 | D1 Urumqi、D12 Urumqi、D13 Singapore | **D1/D12 该有**,D13 纯回程 |
| WBCHET 410 | D1 Ordos | **该有** |
| WBINC9 411 | D1/D9(无景点条目,已在页上显示) | 纯抵离,可以空 |
| WBSZX1 412 | 无 | — |

WBINC9 D2 是另一类(有景点、四级图源都没命中),它一直是可见的——`gaps` 里有它。
两类的处理办法不同,所以 `lib/image_plan.py` 的 `section_gap()` 把成因分成三种
常量(`GAP_NO_MATCH` / `GAP_NO_SUBJECT` / `GAP_NO_ITEMS`),审核页按成因分行显示。

#### 修法,以及为什么不自动补图

`section_gap()` **无条件返回一个 Gap**——`placed == 0` 就记,不再看 `subjects`
是否为空;`subjects` 为空时退到当天的城市(`section.location.en`),那不是一张图,
只是「人还能拿什么去搜」。审核页两桶都全量渲染,缺 gap 记录也照样列出来。

**没有让它自动去搜图。** 这条线全仓库一致:「Stock is never auto-selected」
(compose.py 的注释,理由是搜索按 query 相关性排序、不按是不是那个地方,
6.7 那一串翻车就是证据)。所以这里做到「让人看见」为止,选哪张仍然是人的事。

`GAP_NO_ITEMS`(连景点条目都没有)也照样记 gap,只是审核页把它归到正常那一行。
不按标题去猜「Homeward Bound 是纯回程」——那正是 `make_payload` 的 Trip Type
分类踩过的坑(第 1 节),标题启发式在这里同样不可靠。**记下来,让人判断。**

判断标准和 6.9 是同一条,只是这次漏在了另一个地方:**当一个失败的后果是
「页面上少了东西」时,它必须响。** 6.9 修的是 `materialise` 遇到源文件缺失,
这次漏的是**根本没走到 materialise**——一天连候选都没有,前面就静静地跳过去了。

---

## 7. 与 AI Planner 的关系(阶段二的接点)

AI Planner 的 `module/content` 领域已经做过高度重叠的事:Issue #34
「成品行程 PDF 导入 → 结构化行程+图片 → QA → Skybear 上传闭环」用的样本
**正是 WBCKWE**,已经跑到 test01 并验证通过(travelId=391)。

两边的实际分工现状:

- AI Planner:test01 那一腿已验证;**生产那一腿(Issue #85)建卡后 0 条评论,从没跑过**
- 本项目:直接面向生产,先把三个产品送上去

阶段二的对接点因此很清楚:**本项目往生产写,写完把「哪个行程已上传」回告 AI Planner**,
补上 #85 一直没走的那一步,而不是各自维护一套行程数据。
