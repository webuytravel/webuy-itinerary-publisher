# 从行程册 PDF 到 Skybear 草稿:操作手册

`docs/DESIGN.md` 记的是**为什么**——每条结论怎么验出来的。这份记的是**怎么做**:
一份新册子进来,按什么顺序走,哪一步不能换位置,哪一步必须停下来等人。

2026-08-13 用这套流程送到生产草稿态的产品:
WBCKWE / WBCURC / WBCHET(id 408 / 409 / 410)、WBINC9(411)、WBSZX1(412)。
下面每条都是这几次跑出来的,不是设计意图。

---

## 0. 开工前

- **登录由人做。** Chrome 里 `travel.webuysg.com` 的登录态会过期,过期了就请用户点
  一下 Login,不要代填或代提交密码。
- **图片路径必须在本次会话的工作目录内。** 浏览器扩展的 `file_upload` 只接受
  **会话自己的工作目录**里的文件,其他路径一律拒:

  ```
  Cannot upload "...": only files this session is allowed to read can be uploaded.
  ```

  在 worktree 里跑时,会话的工作目录**就是那个 worktree**,仓库主检出不算。
  所以如果图是在别处生成的(例如在主检出跑的 compose),**先复制进当前工作目录
  再传**。`work/**/out/`、`out_mobile/` 都在 `.gitignore` 里,复制过来不会污染
  版本控制。喂路径用绝对路径。

---

## 1. 先现查生产状态,别信笔记

三件事都要在生产后台看一眼,**每次都看**:

| 查什么 | 在哪 | 为什么 |
|---|---|---|
| 该 type_code 有没有团期 | Package List | wt_travel 不能先于 wt_tour 存在,没团期建不了 |
| 该 type_code 有没有 wt_travel | Package Content Mgmt | 有就不是 NEW |
| **已有的那条是什么状态** | 同上,看 `travelStatus` | **`1 = Published` 是停下来问人的信号,不是 EDIT 模式** |

08-12 记的团期数(8 / 7 / 8)到 08-13 已经变成 20 / 14 / 8。**记录里的生产状态只能
当线索,不能当事实。**

### 1.1 「有就是 EDIT 模式」这条不够用

这条规则是在三个产品都不存在时写的。08-13 下半场四个新册子里有两个撞上了**已发布**
的 wt_travel:WBJGX8 → id 348(线上名字是「SEA-OF-CLOUDS VALLEY…」,和册子标题
完全不同)、WBOHE1 → id 122。

**已发布的记录没有「草稿态」中间状态**——在它上面编辑就是直接改客户看到的页面,
与「只到草稿态」这条红线冲突。**查到 Published 就停下来问用户**,三条路让他选:
跳过、另建一条草稿、或明确授权改线上那条。

### 1.2 用接口查,比点 UI 快且不会看漏

Package List 的 `Tour Code` 筛选框**是个远程筛选的 el-select**,不是文本框——
和 Tour Type 一样,未输入时只挂 20 个选项,「列表里没有」不代表不存在。往
`input.value` 写字符串**完全不生效**。

与其和它搏斗,不如直接打它自己的接口(在后台任意页面的 console 里跑):

```js
// 先抓一次鉴权头:XMLHttpRequest.prototype.setRequestHeader 打补丁后点一下 Search
// 需要的头是 x-wb-tourt-token / Authorization-UserId / X-Web-Deviceid / app_version
const api = (path, body) => fetch('https://apimini.webuy.ren' + path,
  {method:'POST', headers: HDRS, body: JSON.stringify(body)}).then(r=>r.json());

// 团期
await api('/wb_tourt/tour/queryTourListPage',
  {pageNo:1,pageSize:200,tourCode:'WBINC9',tourId:'',areaId:'',tourTypeId:'',
   tourStatus:'',closedStatus:'',trStatus:'',departureAirportId:'',
   startTime:'',endTime:'',tourName:'',paxType:''});
// 展示产品(travelStatus: 0=UnPublished, 1=Published)
await api('/wb_tourt/travelMgmt/queryListPage',
  {pageNo:1,pageSize:50,tourTypeId:'1270',tourTypeName:'',productName:'',
   productId:'',areaId:'',travelStatus:'',paxType:''});
```

`departureTimeFormat` 是 **DD/MM/YYYY**,按字符串排序会得到错的区间。

---

## 2. 行程文本 → `work/<CODE>/itinerary.json`

`lib/pdf_extract_prompt.md` 是给读册子的 agent 的提示词。产出要满足:

- **双语,中文 key 是 `zh`**(产品名例外,用 `{en, zh}` 但落到表单是 enName/chName)。
  写 `.cn` 会静默失效,保存时才报验证错误。
- **产品名不能含 `&`**,换成 `and`。三份册子的标题全都带。
- 每天一个 section,section 下是 `trip_items`(景点卡)。
- **某天没有景点就留空数组**,不要为了填满而编内容(见第 5 步第 7 条)。

---

## 3. 配图 → `work/<CODE>/plan.json`

四级图源,优先级见 `docs/DESIGN.md` 第 3 节:

1. `lib/pdf_images.py` 抽册子内嵌照片 → `pdf_images.json`
2. **人/多模态看图**定 subject 和 verdict → `work/pdf_subjects.json`
   ——**图注会错**。WBCURC 那本 9 张有 3 张图注写错景点(标「铜仁大峡谷」的其实是
   吐鲁番火焰山),因为新疆册子是拿贵州册子改的。WBINC9 那本标着第 2 天博物馆
   段落的其实是黄河石林。主体一律靠看图。
3. `lib/catalogue_source.py` 从 `webuytravel.sg` 同区域在售产品取图(已授权、同风格、
   尺寸对)
4. `lib/mcp_photos.py` 的 `fetch_photo` 补缺口 → `candidates.json`,**看缩略图逐张确认**
   后写进 `bin/compose.py` 的 `OVERRIDES`

然后:

```bash
python3 bin/compose.py WBINC9
```

不带参数会把**所有**产品重跑一遍,包括已经签过字的——那既是多余的网络往返,也会
让已定的配图漂移。产出 `plan.json` + 该产品的审核页。

**源文件缺失时 compose 会直接报错退出,一次列全。** 例如在新检出上跑 WBCURC:

```
WBCURC: 10 placement(s) have no usable source, refusing to materialise:
  section#3 可可托海额尔齐斯大峡谷 — work/WBCURC/cand/d03_keketuohai_canyon.jpg
  section#4 Kanas Three Bays 喀纳斯三湾 — work/WBCURC/raw/p04_1_747x955.png
  ...
Working artefacts (work/**/cand/, cat/, raw/) are gitignored — in a fresh
checkout they exist only after the fetch steps have run.
```

**这不是故障,是提醒你还没跑取图步骤。** `work/**/raw/`、`cand/`、`cat/`、`out*/`
全部在 `.gitignore` 里,克隆下来是空的;`OVERRIDES` 里写的是仓库相对路径,但
**相对路径不等于文件存在**。先跑抽图和取图,再跑 compose。
**这里是人工闸门:`python3 bin/review_page.py WBINC9` 出的页要有人看过并同意,
才往下走。**

### 3.1 `pdf_subjects.json` 的 ref 是页内**全部**栅格的序号

`ref` 形如 `p3#4`,`4` 是 `page.get_images()` 在该页的下标,**包含被 gate 剔除的
furniture**(logo、分隔条、73×70 的小图标)。按「留用图的第几张」去数就会整体错位:
WBINC9 第一次写成了 `p2#1/p2#2/p3#2`,实际是 `p2#2/p2#3/p3#4`,后果是一百零八塔
被当成木活字印刷、路线图被贴上塔的标签、而阿拉善湖那条指到了一块 73×70 的装饰块
(于是那天变成 gap)。

写完立刻打一遍验:

```bash
python3 -c "
import json; from pathlib import Path
d=json.load(open('work/pdf_subjects.json'))['WBINC9']
raw={f\"p{r['page']}#{r['index']}\":r for r in json.load(open('work/WBINC9/pdf_images.json'))}
for row in d:
    r=raw[row['ref']]; print(row['ref'], r['kind'], f\"{r['width']}x{r['height']}\", '->', row['subject'])
"
```

`kind` 和尺寸对不上主体,就是错位了。

---

## 4. 规格化 → `work/<CODE>/form_payload.json`

三步,顺序不能反(`resharpen` 会改写 `plan.json` 里的 `src_path`/`bytes`):

```bash
python3 bin/resharpen.py    WBINC9 --assets-root .   # stock 预览图换成原图重编码
python3 bin/mobile_crops.py WBINC9 --assets-root .   # 补竖版轮播(必填槽位)
python3 bin/make_payload.py WBINC9 --assets-root .   # 合成注入用的 payload
```

- **`resharpen` 不改选片**,只是把 Pexels `?w=940` / Unsplash `&w=1080` 的预览图换成
  同一张照片的原图。WBCHET 全部 18 张因此从上采样 1.7–2.3× 变成下采样 0.2–0.9×。
- **`mobile_crops` 从原始源图重裁**,不是拿 4:3 成品再切一刀。
- `make_payload` 里的 `HOUSE_HIGHLIGHTS` 是编辑决策(6 条版式,见第 5 步),
  新产品要**先补上这一项**,否则会 KeyError。

### 4.1 轮播要 1080px 以上的源图,册子图进不去

竖版 `Mobile Display Image` 是 **1080×1440**,从一张 685×443 的册子图里能裁出的竖窗
只有 332px 宽 → **放大 3.25×**,肉眼就是糊的。而册子图**没有办法再取大**——
`resharpen` 只能改写 Pexels/Unsplash 那种把尺寸写在 query 里的 URL。

所以规则是:**册子图只放当天的 section 槽(尺寸够),轮播另外挑高分辨率的源。**
`bin/compose.py` 的 `CAROUSEL` 就是干这个的——按位置显式列出 8 张:

```python
CAROUSEL = {
    "WBINC9": [("hero_yellow_river", 4, "理由"), ...],          # stock 块 + 序号
    "WBSZX1": [("cat:Jmz4i0ph", 0, "理由"), ...],               # cat: 前缀取图库图
}
```

给它的每一张都要先看过。没有 `CAROUSEL` 条目时走老路(图库剩图,没有图库就复用
当日配图),那条路是**不看分辨率**的。

### 4.2 图库图不是都能用,要在源头挑

`work/catalogue.json` 是照单全收采下来的,里面混着两类不能用的:

- **列表横幅图**:`alt` 就是产品名(「7D6N Canton Gourmet Tour 2.0」)。**每个
  tours/* 的第 0 条都是它**,四个采过的产品无一例外。它排在 pool 最前面,于是
  成为轮播首图,又被复制成 List Thumbneil——408 和 409 就是这样带着兄弟产品的
  横幅图当缩略图上线的。token 匹配还会把它配到任意一天去,WBSZX1 第 4 天中过。
- **CMS 里本来就小的图**:tours/118 的岭南新天地和广东千古情只有 ~380×510,任何
  槽位都要放大 3 倍以上。

两类都**从 `catalogue.json` 里删掉**,而不是等它们进了 plan 再挑。下载后量一遍:

```bash
python3 -c "
from PIL import Image; from pathlib import Path; import json
for iid, alt in json.load(open('work/catalogue.json'))['tours/118-7d6n-canton-gourmet-tour-2-0']:
    p=Path('work/WBSZX1/cat')/f'{iid}.jpg'
    print(iid, Image.open(p).size if p.exists() else '(未下载)', alt)
"
```

---

## 5. 生产表单:顺序不能换

在 `#/packageDisplayMgmt/editDisplayDetail?type=add` 上:

**1) 选 Tour Type。** 两条路,**优先走组件那条**:

```js
const inp = document.querySelector('input[placeholder="Select Tour Type"]');
const vm  = inp.closest('.el-select').__vue__;
vm.remoteMethod('WBINC9');            // 服务端筛选,几秒后 vm.options 只剩一条
// 等 3–4 秒,确认 vm.options.length === 1 且 label 以该代码开头,再:
vm.handleOptionSelect(vm.options.find(o => /^WBINC9\b/.test(o.label)));
```

`handleOptionSelect` 就是真实点击走的那个入口,所以这是真选中不是画上去的。
注意 `vm.handleQueryChange('WBINC9')` **不生效**(不会触发远程请求),要用
`vm.remoteMethod`。

另一条是点 UI:用元素 ref 点输入框(**不要用屏幕坐标**,坐标会落回输入框把筛选词
清空),等 2–3 秒打代码,等 3–4 秒,再点选项。
**点完立刻回读是空值,这是正常滞后——在这里重试会把已选中的取消掉。**
该下拉未聚焦时 `readOnly` 是 `true`,聚焦后才 `false`;别据此判定它不可筛选。

> 🚨 **选中 Tour Type 有可能把整个标签页卡死。** 08-13 实测点选项那一下超时 45s,
> 之后该页所有脚本注入全部 5s 超时,**而且连累同一 MCP 标签组里的其他标签页**。
> 换 hash、甚至带 query 强制整页重载都救不回来。
> **恢复办法是开一个新标签页**(`tabs_create_mcp`),把卡死的关掉,在新页重来。
> 表单在点 Save 之前什么都不写库,所以重来是安全的。

**2) 注入 `lib/form_filler.js` 和 payload。** payload 直接内联进 JS,不要走 fetch。

**3) 覆盖产品名。** 选中 Tour Type 会**自动填成带 `&` 的册子标题**,自动填的值不能信。

**4) Highlight 填 6 条。** 表单只有 6 组输入且没有加行控件——**6 是版式不是限制**,
线上 `tours/115` 也正好 6 条:4 条头部景点/体验 + 2 条用 `·` 压缩的餐食风味。
行程文件里的 15–22 条要按这个版式重排,写进 `HOUSE_HIGHLIGHTS`。

**5) 建 section 和 trip item:同步连点。**
点一次 `Add Section` 就重渲染整个行程区,开销随已有 section 数增长。写成
「点 → await → 再点」的循环,13 天那个产品**跑了二十多分钟没填完**。
Vue 是批处理的:**一个同步块里连发 N 次 click 只产生一次重渲染**,同样的表单 16 秒完成。
代价是同步块前后拿到的元素全部作废——写进已 detach 的 input 会「成功」但什么也不改。
所以是:**连点 → 等一次 → 重新查询 → 填字段。**

**6) 填字段。** 文本进 v-model 要用原型 setter + 冒泡 `input` 事件;直接赋 `.value`
只进 DOM,提交时是空的。`Trip Type` 是 el-select,用
`item.querySelector('.el-select').__vue__.handleOptionSelect(option)`,不用点下拉。

**7) 没有景点的天:删掉自带的空行。**
每个 section 自带一条 trip item,而 Trip Type / Trip Title 都是必填,空着会卡验证。
**要删,不要编内容填。** 三个坑:
- **折叠状态下删不掉**——移除动画停在 `el-list-leave` 不结束,DOM 里那条还在。
  先展开 section(点 `.el-collapse-item__header`)再删。
- 一次 Delete 只出一个确认框。**多点一次就多一个,后面那个必须 Cancel**——
  确认它会删掉别的条目。
- **点完 Confirm/Cancel 立刻回读,会看到一个「幻影弹窗」**:`.el-message-box`
  在淡出动画期间仍然 `offsetParent !== null`。08-13 因此误判成排队,又多点了几次
  Cancel。**等 2 秒再判断**,并且以 trip item 的实际条数为准,不以弹窗数为准。

**8) 最后挂图。** ——**选中 Tour Type 会清空已上传的图片**,所以挂图只能放在最后。
用 `find` 拿各槽位的 ref,再用扩展的 `file_upload` 喂本地路径。槽位对应:

| 槽位 | 喂什么 |
|---|---|
| List Thumbneil | `out/thumbnail_00_0.jpg` |
| Desktop Display Image | `out/carousel_*.jpg`(横版) |
| Mobile Display Image | `out_mobile/carousel_*_mobile.jpg`(竖版,必填) |
| Route Map | `out/route_map_00.png` |
| Section Photos(每天一个) | `out/section_<day>_*.jpg`,文档序 = 天序 |
| Trip Photos / Cover Video | 留空(非必填) |

> **不要用本地 http 服务器 + fetch 取字节。** 从 https 页面 fetch `127.0.0.1`
> **静默挂起**:promise 既不 resolve 也不 reject,console 一条报错都没有,看起来像
> 自己的代码写错了。「Chrome 对 loopback 豁免混合内容」这条对 `fetch` 不成立。

**9) 发布框:回读 + 截图,两样都要。**
`Publish for sale` 的默认值**不可预设**——08-06 是默认已勾,08-13 三次新建都是未勾。
所以规则不是记住默认值,而是**每次保存前都回读 DOM 并截图看渲染结果**。
需要取消时:点掉 → **等 2 秒** → 再回读(class 比 input 慢一拍,读太早会误判失败而
重复点,反而勾回去)。

**10) 点可见的那个 Save。**
页面上有四个按钮叫 Save/Confirm,三个在隐藏弹窗里。点到隐藏的那个**没有任何反应也
没有报错**,看起来像保存卡住。按 `offsetParent !== null` 过滤。

**11) 团期。** 选中 Tour Type 时系统会自动加载团期并**全部勾上**,通常不用手动动。
保存前扫一眼数量对不对。

---

## 6. 保存后必须回读

回列表页确认 `Status = Unpublished`,记下 Product Id。然后**重新打开编辑页**核对:
产品名(无 `&`)、highlights 条数、section 数、trip item 数、各图片槽位数量、
`Publish for sale` 未勾、团期已绑。

表单在点 Save 之前什么都不写库,**填写阶段中断是安全的**;一旦保存就是生产记录。

---

## 6.1 改已有产品的图(EDIT 模式)

2026-08-13 给 408 / 409 换掉列表缩略图和轮播时踩到的,和新建流程不一样:

**1) 换产品要整页重载,不能只改 hash。**
从 `?id=408` 直接跳到 `?id=409`,地址栏变了,**页面数据不变**——SPA 在同一路由内
不会重新拉。实测跳过去之后产品名还是 408 的贵州重庆,如果不核对就接着删图上传,
改的是同一个产品两次。加个查询串强制整页重载:

```
https://travel.webuysg.com/?v=409#/packageDisplayMgmt/editDisplayDetail?id=409&type=edit
```

**每次进编辑页都先读一次 Product Name 确认是对的那个产品。**

**2) 删图:组件的模型是真相,DOM 不是。**
图片槽位是自定义组件 `image-crop-upload`,删除按钮在 hover 才显示的
`.img-btns > i.el-icon-delete` 里。删掉之后**图还留在 DOM 上**——移除动画停在
`el-list-leave` 不结束,和删 trip item 那个坑一模一样。所以数 `<img>` 会得到旧数字,
要读组件的 `value`:

```js
const vmOf = name => {                       // name 是表单标签,如 'Desktop Display Image'
  const f = [...document.querySelectorAll('.el-form-item')]
    .find(x => (x.querySelector('.el-form-item__label')||{}).innerText?.trim() === name);
  return f.querySelector('.image-crop-upload').__vue__;
};
const vm = vmOf('Desktop Display Image');
while (vm.value.length) { vm.removeImage(0); await new Promise(r => setTimeout(r, 200)); }
```

**3) 连续删多张会让注入调用超时,但操作本身完成了。**
一次删七八张,`Runtime.evaluate` 会报 45s 超时(每次删都触发重渲染)。
**不要直接重试**——先等 20 秒再回读 `vm.value.length`,通常已经是 0 或只剩几张,
接着删剩下的即可。盲目重试会在别的槽位上多删。

**4) 只动要动的槽位,别碰 Tour Type。**
选中 Tour Type 会清空所有已上传的图(第 5 步第 8 条)。改图时**完全不要碰它**。
删改前后各读一次 Route Map 和 Section Photos 的数量,确认没有误伤。

**5) 保存前仍然要回读 + 截图确认发布框。** 编辑已有产品和新建一样,
`Publish for sale` 勾着保存就是当场上架。

---

## 7. 已知留空的字段

Trip Photos、Cover Video Asset、Flight Info 都非必填,当前流程留空(当天配图挂在
Section Photos)。Tour Fare 表显示 `No Data`——定价不在本流程范围内。

**这条会漏掉真实的商务信息。** WBSZX1 册子上印着「必需自费项目 RMB 600/人」
(广东千古情 + 珠江夜游 + 石景山缆车,大人小孩同价)。当前流程**没有任何字段
承载它**——Important Note、Flight Info 都留空,Tour Fare 是 `No Data`。
遇到册子上有必需自费 / 强制小费 / 单房差这类条目,**在交付时单独告诉用户**,
不要因为表单里没地方放就当它不存在。

---

## 8. 每个新产品要动的文件清单

按顺序,少一样就会在后面某一步炸:

| 文件 | 加什么 | 不加会怎样 |
|---|---|---|
| `work/<CODE>/itinerary.json` | 双语行程(key 是 `zh`) | — |
| `work/pdf_subjects.json` | 该册子每张图的 ref / subject / verdict | 册子图全部不参与配图 |
| `bin/compose.py` `PRODUCTS` | `"<CODE>": ("CHN", [同区域在售产品 slug])` | KeyError |
| `bin/compose.py` `OVERRIDES` | 自动匹配配不出或配错的天 | 那些天留 gap 或配错图 |
| `bin/compose.py` `CAROUSEL` | 8 张高分辨率轮播(可选但强烈建议) | 轮播可能全是册子小图,竖版发虚 |
| `bin/make_payload.py` `HOUSE_HIGHLIGHTS` | 6 条 | **KeyError** |
| `work/catalogue.json` | 新采的同区域产品图(记得剔横幅图和 <1080px 的) | 图库这一级为空 |
