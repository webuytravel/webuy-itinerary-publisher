# PDF extraction prompt template

> Used by `skills/skybear-upload-package/SKILL.md` step 2 (EXTRACT).
> Run this against the PDF (or per-page PNGs if PDF > 20MB) using Claude
> multimodal Read.

---

You are reading a Skybear travel package brochure (English + Chinese bilingual).

Extract the following fields and return as YAML. Be conservative: if a field
is not on the PDF, omit it (do NOT make up values). Translation is not your job
— the PDF already contains both languages, copy them as-is.

```yaml
tour_type:
  type_code: <e.g. WBMXMN; usually printed as "Tour code: WBMXMN" or in the
              file name>
  type_name_en: <main English title, e.g. "7D6N HAKKA HOMELAND × MINNAN
                 CULTURAL DISCOVERY — TRAVEL WITH MARCUS CHIN">
  type_name_cn: <main Chinese title, e.g. "7天6晚穿越客家原乡 × 闽南文化深度之旅
                 — 与陈建彬同行">
  travel_days: <int, e.g. 7 from "7D6N">

departure_date_hint: <e.g. "2026-12-10" if PDF cover shows "10 December 2026";
                      else omit>

travel:
  product_name_en: <usually same as type_name_en>
  product_name_cn: <usually same as type_name_cn>
  cities_en: [<list of cities visited, e.g. "Xiamen", "Quanzhou", "Yongding",
               "Dapu", "Meizhou", "Shantou", "Chaozhou">]
  cities_cn: [<同上 in Chinese>]
  meal_plan_summary: <e.g. "6 Breakfasts / 6 Lunches / 6 Dinners">
  accommodation_level: <e.g. "Local 5 Star Hotel / 全程当地 5 星">
  starting_price_hint: <if PDF shows a "from $XXXX" cover price, copy as
                        decimal; else omit>
  important_note_en: <Important Note / Disclaimer / T&C English text, often a
                      footer paragraph; multi-line OK>
  important_note_cn: <对应的中文段>
  highlights:
    - en: <highlight 1 English>
      cn: <highlight 1 中文>
    - en: ...
      cn: ...
    # PDFs typically have 4-6 highlights
  sections:
    - sort_num: 0   # DAY 1
      title_en: <e.g. "SINGAPORE → XIAMEN → 1.5H QUANZHOU">
      title_cn: <e.g. "新加坡 → 厦门 → 1.5h 泉州">
      location_en: <e.g. "Quanzhou"; usually a single city>
      location_cn: <e.g. "泉州">
      description_en: <attractions + meal markers, e.g.
                      "Lunch / Dinner. Wudianshi Traditional Culture
                       District: ... ">
      description_cn: <对应中文>
    - sort_num: 1   # DAY 2
      ...
    # one section per day, sort_num 0..(travel_days-1)
```

## Rules

1. **Bilingual fidelity**: extract both languages exactly as printed.
   No paraphrasing. No copyright concerns inside Webuy's own content.
2. **Section count**: must equal `travel_days`. If you can't find a clear
   "DAY N" header, surface this issue rather than guessing.
3. **Sort numbering**: `sort_num` starts at 0 (matches `wt_travel_section`
   convention seen in other UAT records).
4. **No invented data**: if the PDF doesn't list inclusions / remarks /
   pricing / flight numbers, simply omit those keys. Planner will fill in
   chat. Never write "TBD" or placeholder text.
5. **Ignore marketing decorations**: ✦ ★ ? icons in the PDF are decorative;
   strip or keep at your discretion as long as descriptions read naturally.
6. **Hotels**: PDF often lists per-night hotels on page 2. If present, append
   to the relevant section's `description_cn` as `夜宿: <hotel>`. If unclear
   per day, list them on the LAST section's description as a summary block.

## Output

Return ONLY the YAML block — no preamble, no closing commentary. The next
step in the SKILL pipeline parses it directly.
