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
