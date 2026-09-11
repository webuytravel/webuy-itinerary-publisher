#!/usr/bin/env python3
"""迁移前后逐个产品比对 plan —— issue #4 Done When 第 1 条的那道主闸。

配图已经人工签过字。这次重构如果不是等价变换,后果是线上产品的图悄悄换掉,
而**管线里没有任何一处会报错**:摘要行只数张数,审核页只渲染 plan 里有什么。
所以唯一靠得住的验收方式是拿迁移前的源码和迁移后的源码各跑一遍,逐字节比。

    python3 tools/verify_equivalence.py                 # 全部 17 个产品
    python3 tools/verify_equivalence.py WBCHET WBCKWE   # 只比这两个

## 比的是 plan,不是 plan.json 落盘的那一刻

`bin/compose.py` 的 `__main__` 在写 plan.json 之前会先 `materialise()`,把每张
选中的图裁剪编码到 `work/<CODE>/out/`。而那一步要的原始栅格
(`work/**/cand/`、`cand_commons/`、`cat/`、`raw/`)是 gitignored 的,一个干净
clone 里一张都没有,缺一张 `materialise` 就整个退出。所以这里跑到
`assign_trip_photos` 为止 —— 那正好是**这次重构改到的全部范围**:选片从哪里来。
`materialise` / `render` 两步在 lib 里,本次一行没动,而且它们的输入就是这里比完
的 plan。out_path / bytes / upscale 三个字段由 materialise 填,两边都空着。

比对的产物写在 `--out` 下,`before/<CODE>.json` 和 `after/<CODE>.json`,
不一致时直接 `diff` 这两个文件看。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_REF = "9b5ef5c"  # PR #3 合入后、本次迁移之前的 origin/main


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _no_network(module) -> None:
    """图库图只要路径,不要真去 OSS 拉。

    `pull_catalogue` 在文件不存在时会下载;这里把下载换成 no-op,它仍然照原样
    往 row["path"] 写同一个路径。两边都打同一个桩,所以不影响比对结论。
    """
    module.fetch_catalogue = lambda image, dest: None


def plan_before(module, code: str) -> tuple:
    """迁移前 `__main__` 里从 compose 到 assign_trip_photos 的那一段,原样。"""
    work = module.WORK
    region, tours = module.PRODUCTS[code]
    plan = module.compose(code, region, tours, module.OVERRIDES.get(code, {}))
    cand = work / code / "candidates.json"
    stock = json.loads(cand.read_text("utf-8")) if cand.exists() else {}
    module.fill_carousel(plan, code, tours,
                         picks=module.CAROUSEL.get(code), stock=stock)
    removed = module.dedupe(plan, cross_slot=bool(tours))
    itin = json.loads((work / code / "itinerary.json").read_text("utf-8"))
    module.assign_trip_photos(plan, itin["sections"], module.score,
                              module.MATCH_FLOOR,
                              extra=module.trip_pool(
                                  code, module.TRIP_PICKS.get(code, [])))
    return plan, removed


def dump(plan, removed) -> str:
    """和 `ImagePlan.to_json` 同一套序列化参数,外加被去重删掉的那几张。

    `removed` 也要比:它进不了 plan.json(`dedupe` 返回的是一串人读的说明),
    但它是摘要行里 `deduped=` 那个数,而且「哪几张被判成重复删掉了」本身就是
    一条编辑结果。
    """
    return json.dumps({"plan": asdict(plan), "deduped": list(removed)},
                      indent=2, ensure_ascii=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("codes", nargs="*", help="不给就跑全部有 editorial.json 的产品")
    ap.add_argument("--ref", default=DEFAULT_REF, help="迁移前的 git ref")
    ap.add_argument("--out", type=Path, default=Path(".verify"),
                    help="两边的 plan 转储写到这里")
    args = ap.parse_args()

    before_src = args.out / f"compose_{args.ref}.py"
    before_src.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(["git", "show", f"{args.ref}:bin/compose.py"],
                          capture_output=True, text=True, check=True)
    before_src.write_text(proc.stdout, "utf-8")

    before = _load_module("compose_before", before_src)
    after = _load_module("compose_after", REPO / "bin" / "compose.py")
    _no_network(before)
    _no_network(after)

    codes = args.codes or after.editorial.codes(after.WORK)
    missing = sorted(set(codes) - set(before.PRODUCTS))
    if missing:
        raise SystemExit(f"{missing} 在迁移前的 PRODUCTS 里不存在,无从比对")

    (args.out / "before").mkdir(parents=True, exist_ok=True)
    (args.out / "after").mkdir(parents=True, exist_ok=True)
    differ = []
    for code in codes:
        old = dump(*plan_before(before, code))
        new = dump(*after.run(code))
        (args.out / "before" / f"{code}.json").write_text(old, "utf-8")
        (args.out / "after" / f"{code}.json").write_text(new, "utf-8")
        same = old == new
        if not same:
            differ.append(code)
        print(f"  {code:<10} {'同' if same else '★ 不一致'}  "
              f"{len(json.loads(old)['plan']['placements'])} 张")

    print(f"\n{len(codes)} 个产品,{len(codes) - len(differ)} 个逐字节一致")
    if differ:
        print(f"不一致:{differ} —— diff {args.out}/before/<CODE>.json "
              f"{args.out}/after/<CODE>.json")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
