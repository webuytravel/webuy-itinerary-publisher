# 从行程册 PDF 到 Skybear 草稿:操作手册

`docs/DESIGN.md` 记的是**为什么**——每条结论怎么验出来的。这份记的是**怎么做**:
一份新册子进来,按什么顺序走,哪一步不能换位置,哪一步必须停下来等人。

2026-08-13 用这套流程把 WBCKWE / WBCURC / WBCHET 三个产品送到生产草稿态
(product id 408 / 409 / 410)。下面每条都是那次跑出来的,不是设计意图。

---

## 0. 开工前

- **登录由人做。** Chrome 里 `travel.webuysg.com` 的登录态会过期,过期了就请用户点
  一下 Login,不要代填或代提交密码。
- **图片路径必须在本次会话可读目录内。** 浏览器扩展的 `file_upload` 会拒掉仓库主检出
  之外的路径。`work/**/out/`、`out_mobile/`、`cand/` 都在 `.gitignore` 里,直接复制进
  当前工作目录即可。

---

## 1. 先现查生产状态,别信笔记

两件事都要在生产后台看一眼,**每次都看**:

| 查什么 | 在哪 | 为什么 |
|---|---|---|
| 该 type_code 有没有团期 | Package List | wt_travel 不能先于 wt_tour 存在,没团期建不了 |
| 该 type_code 有没有 wt_travel | Package Content Mgmt 按关键词搜 | 有就是 EDIT 模式,没有才是 NEW |

08-12 记的团期数(8 / 7 / 8)到 08-13 已经变成 20 / 14 / 8。**记录里的生产状态只能
当线索,不能当事实。**

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
   吐鲁番火焰山),因为新疆册子是拿贵州册子改的。主体一律靠看图。
3. `lib/catalogue_source.py` 从 `webuytravel.sg` 同区域在售产品取图(已授权、同风格、
   尺寸对)
4. `lib/mcp_photos.py` 的 `fetch_photo` 补缺口 → `candidates.json`,**看缩略图逐张确认**
   后写进 `bin/compose.py` 的 `OVERRIDES`

然后:

```bash
python3 bin/compose.py
```

产出 `plan.json` + 每个产品的审核页。**这里是人工闸门:`bin/review_page.py` 出的
汇总页要有人看过并同意,才往下走。**

---

## 4. 规格化 → `work/<CODE>/form_payload.json`

三步,顺序不能反(`resharpen` 会改写 `plan.json` 里的 `src_path`/`bytes`):

```bash
python3 bin/resharpen.py --assets-root .      # stock 预览图换成原图重编码
python3 bin/mobile_crops.py --assets-root .   # 补竖版轮播(必填槽位)
python3 bin/make_payload.py --assets-root .   # 合成注入用的 payload
```

- **`resharpen` 不改选片**,只是把 Pexels `?w=940` / Unsplash `&w=1080` 的预览图换成
  同一张照片的原图。WBCHET 全部 18 张因此从上采样 1.7–2.3× 变成下采样 0.2–0.9×。
- **`mobile_crops` 从原始源图重裁**,不是拿 4:3 成品再切一刀。
- `make_payload` 里的 `HOUSE_HIGHLIGHTS` 是编辑决策(6 条版式,见第 5 步),
  新产品要**先补上这一项**,否则会 KeyError。

---

## 5. 生产表单:顺序不能换

在 `#/packageDisplayMgmt/editDisplayDetail?type=add` 上:

**1) 选 Tour Type。** 用元素 ref 点输入框(**不要用屏幕坐标**,坐标会落回输入框把筛选词
清空),等 2–3 秒,打产品代码,等 3–4 秒服务端筛到唯一一条,点它。
**点完立刻回读是空值,这是正常滞后——在这里重试会把已选中的取消掉。**
该下拉未聚焦时 `readOnly` 是 `true`,聚焦后才 `false`;别据此判定它不可筛选。

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
**要删,不要编内容填。** 两个坑:
- **折叠状态下删不掉**——移除动画停在 `el-list-leave` 不结束,DOM 里那条还在。
  先展开 section(点 `.el-collapse-item__header`)再删。
- 确认弹窗**会排队**。多点一次就多一个框,后面那个必须 **Cancel**,确认它会删掉别的条目。

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

## 7. 已知留空的字段

Trip Photos、Cover Video Asset、Flight Info 都非必填,当前流程留空(当天配图挂在
Section Photos)。Tour Fare 表显示 `No Data`——定价不在本流程范围内。
