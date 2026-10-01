# Replicate 1 gate: final decision and language decomposition

Queries `data/queries_294.jsonl` sha256 `ac600a31e74a2124a0fd70ba287f0bbe7f2e2c292d2e3026fad48167c586ca5d`. Caps 8192 / 32768. Scoring pin `3be49a0` 2026-08-21T13:23:26Z. cap_hit pin `e5932f3` 2026-08-22T07:26:52Z. Run A = `results/phase2`. Run B = `results/replicate1`. Seed 42 / temp 0 is not bit-identical.

Completed `{ok, parse_failed, cap_hit}`. Retry leftover after budget 3 is infra: not in oracle. parse_failed and cap_hit count as correct=0 on matrix 294. Bodies forbidden. `audit_labels` 14×2 files: n=294, forbidden_hits=[], extra_keys=[]. Labels have no generation-id field.

## Final decision

**The decision is not “build a learned router.”**

확정 판정문:

> 전체 갭 31셀 중 버킷 내 12, 버킷 간 19. 버킷 내 12 중 coding 9.
> 나머지 6개 버킷 합계 3셀은 지터 바닥(9셀) 아래다.
>
> 결론: 태스크 타입 분류기가 갭의 약 61%를 공짜로 가져간다.
> 그 위에 학습된 라우터가 추가로 벌 수 있는 건 사실상 coding 버킷뿐이다.
>
> 이 판정은 “라우터가 유효하다”가 아니다.

On naive A all-cells, the 31-cell oracle−best_single gap decomposes into
**12 within-bucket cells** and **19 between-bucket cells**. A task-type
classifier therefore captures **19/31 = 61.3%** of the gap without learned
routing. Of the 12 within-bucket cells, **9 are coding**. The other six
buckets together contribute only **3 cells**, below the predeclared
9-cell jitter floor. Above task-type classification, the only material
remaining opportunity for a learned router is the coding bucket.

Do not collapse this to “routing is useful.” The result is: **task type gets
about 61% for free; learned routing has a material residual only in coding.**

The main estimate is **stable × all-cells**, gap **29/294 = 0.0986**, because
stable is the only rule here that does not absorb one-run upward oracle noise.
All other six variants remain beside it. best_single changes across the
measurement contract (`fable/opus`, `opus`, `qwen`, `gemini_3_7_flash`);
which model is “best” is itself protocol-dependent.

## Audit

Expected 14×294=4116 last-per-key on A and on B: **4116 / 4116**. No missing keys.

Infra leftover A: **2** — `gpt_5_6_sol` and `gpt_5_6_luna` `coding:abc390_c` ko `sandbox_error` attempt 3.

Infra leftover B: **1** — `gpt_5_6_luna` `coding:abc390_c` ko `sandbox_error` attempt 3. Sol B scored that cell (`ok`, correct=0).

cap_hit A **43**, B **50**. parse_failed A **56**, B **56** (same total, different composition).

### cap_hit by model

| model | A | B |
|---|---:|---:|
| gpt_5_6_sol | 0 | 0 |
| gpt_5_6_terra | 0 | 0 |
| gpt_5_6_luna | 0 | 0 |
| claude_fable_5 | 1 | 0 |
| claude_opus_5 | 2 | 1 |
| claude_sonnet_5 | 4 | 7 |
| gemini_3_1_pro | 3 | 3 |
| gemini_3_7_flash | 0 | 0 |
| grok_4_6 | 3 | 3 |
| grok_4_3 | 0 | 0 |
| deepseek_v4_pro | 10 | 9 |
| deepseek_v4_flash | 4 | 8 |
| kimi_k3 | 4 | 6 |
| qwen3_7_plus | 12 | 13 |
| **sum** | **43** | **50** |

### parse_failed by model (not cap)

| model | A | B |
|---|---:|---:|
| gpt_5_6_sol | 2 | 1 |
| gpt_5_6_terra | 2 | 2 |
| gpt_5_6_luna | 3 | 4 |
| claude_fable_5 | 4 | 7 |
| claude_opus_5 | 1 | 1 |
| claude_sonnet_5 | 2 | 0 |
| gemini_3_1_pro | 1 | 2 |
| gemini_3_7_flash | 6 | 6 |
| grok_4_6 | 17 | 15 |
| grok_4_3 | 16 | 13 |
| deepseek_v4_pro | 1 | 0 |
| deepseek_v4_flash | 1 | 0 |
| kimi_k3 | 0 | 4 |
| qwen3_7_plus | 0 | 1 |
| **sum** | **56** | **56** |

Grok 33→28. gemini_3_7_flash 6→6 (same abstention 6). Remainder 17→22.

Billed `usage.cost` A **51.557488**, B **49.591932**, Δ **−3.81%**.
That is the cost-axis noise floor for Pareto (billed primary).

Cost-null decision: **exclude-cell, keep-model**. The one missing billed cell
in both runs is `claude_opus_5|toolcall:parallel_multiple_139|en`. It is
`parse_failed`, correct=0; only its cost is unknown. Report the Opus cost on
**293 billed cells** (A **8.311260**, B **7.066535**), retain its Pareto
point, and state that denominator. Do not substitute catalog cost. Removing
a best_single candidate because 1/294 costs is missing loses more information
than retaining a clearly qualified 293-cell cost coordinate.

## gemini_3_7_flash 0 flips is not A copied into B

Correct bit identical 294/294, cap_hit 0/0, parse_failed 6/6. Labels rows identical: **0/294**. latency_ms identical: **0/294**. latency sum A 1692059 vs B 1916468. billed 0.468923 vs 0.469771. completion_tokens 237769 vs 238221. prompt_tokens 61617=61617. 292/294 cells share cost and completion_tokens; **2** cells differ in tok/cost. Not resume reuse of A rows.

gemini_3_1_pro: identical rows 0/294, same latency 0/294, billed 7.109740 vs 6.938848.

## Why cap_hit-excluded exists and parse_failed-excluded is the symmetric check

cap_hit is our `max_tokens` design (`e5932f3`): the cell is completed, correct=0, not infra. Excluding it asks whether pile-up on qwen/pro is an ability ranking or a cap ranking. parse_failed is the model missing the output contract (Grok diagnosis pin `aa30e9b`: format failure, no parser widening). It is also completed correct=0. Oracle does not change when either class is dropped from the pool (already 0). best_single **n** shrinks. Both exclusions are reported. cap-excluded is not privileged as “the” gate.

## Jitter floor (before any gate number)

A vs B scored-correct flips: **221 / 4116** (5.37%). **115** 1→0, **106** 0→1.

By model (1→0 / 0→1): sonnet 16/12, flash 16/16, grok_4_3 11/16, grok_4_6 7/16, fable 11/6, luna 10/7, kimi 11/4, qwen 10/5, pro 9/9, opus 4/7, terra 4/3, sol 3/4, gemini_3_1_pro 3/1, gemini_3_7_flash **0/0**.

By bucket: coding 73, knowledge 49, toolcall 41, extraction 21, abstention 20, instruction 16, math 1.

By lang: hi 83, en 74, ko 64.

Recap smoke had ≥9/294 1→0 vs the 1024-cap run. Grok 33 replay accepted ~11/66. Gaps smaller than ~9/294 = 0.0306 are not a router signal.

## Seven variants (item n=294 unless noted)

Oracle item = 1 iff some **usable** model cell is correct. Usable = not infra. cap/parse exclusions also drop those statuses from that model’s pool. naive A uses run A only. naive B uses run B only. stable requires the same model correct on **both** A and B.

best_single = argmax model accuracy on the same filter. naive_all: fable and opus **tie** 249/294.

| role | variant | oracle | best_single | gap |
|---|---|---|---|---|
| sensitivity | naive A × all-cells | 280/294 = 0.9524 | fable = opus 249/294 = 0.8469 | 0.1054 |
| sensitivity | naive B × all-cells | 277/294 = 0.9422 | opus 252/294 = 0.8571 | 0.0850 |
| **main** | **stable × all-cells** | **274/294 = 0.9320** | **opus 245/294 = 0.8333** | **0.0986** |
| sensitivity | naive A × cap_hit-excluded | 280/294 = 0.9524 | qwen 248/282 = 0.8794 | 0.0729 |
| sensitivity | stable × cap_hit-excluded | 274/294 = 0.9320 | qwen 238/280 = 0.8500 | 0.0820 |
| sensitivity | naive A × parse_failed-excluded | 280/294 = 0.9524 | fable 249/290 = 0.8586 | 0.0938 |
| sensitivity | stable × parse_failed-excluded | 274/294 = 0.9320 | gemini_3_7_flash 244/288 = 0.8472 | 0.0848 |

All listed: oracle > best_single, gap 0.073–0.105, all above 9/294. Split: **who** is best_single. cap/parse exclusions change n per model; they are not 294-denom rankings. Grok does not become best_single under parse exclusion (naive A grok_4_3 229/278 = 0.8237, grok_4_6 227/277 = 0.8195).

The `fable/opus/qwen/gemini_3_7_flash` best_single split is an envelope-style
finding: “best model” depends on the measurement contract, not only ability.

Stable exclusions use **A∪B** unusable cells for that model. qwen cap_hit A 12, B 13, intersection 11, union 14 → stable cap-excluded n=294−14=280. gemini_3_7_flash parse_failed 6/6 same keys → stable parse-excluded n=288.

`stable` rewards bit-stability. gemini_3_7_flash has 0 correct-bit flips so stable=naive for that model and can win stable×parse-excl (244/288) by determinism. sonnet 16 1→0 and flash 16 1→0 lose 16 cells on stable. Who is best_single can be a stability ranking, not only an ability ranking.

## Infra-2 sensitivity

Drop item `coding:abc390_c` ko. A fable and A opus are both correct=1 on that item, so both become **248/293 = 0.8464**. naive oracle 279/293 = 0.9522, gap 0.1058 vs the tied pair. stable 273/293 = 0.9317 vs opus 244/293, gap 0.0990. Gap movement < 0.001. Gate is not sensitive to those 2 cells.

## Overall / by-bucket / by-lang (A all-cells)

Naive A matrix correct: fable 249, opus 249, sonnet 248, qwen 248, kimi 247, gemini_3_1_pro 246, gemini_3_7_flash 244, sol 242/293, terra 238, pro 236, luna 233/293, grok_4_3 229, grok_4_6 227, flash 226.

Stable both-correct: opus 245, gemini_3_7_flash 244, gemini_3_1_pro 243, sol 239/293, fable 238, qwen 238, kimi 236, terra 234, sonnet 232, pro 227, luna 223/293, grok_4_6 220, grok_4_3 218, flash 210.

Naive by bucket (oracle / best / gap): knowledge 41/42 vs opus 40, gap 1/42; math 42/42 vs fable 42, gap 0; instruction 38/42 vs gemini_3_1_pro 36, gap 2/42; extraction 42/42 vs opus 42, gap 0; toolcall 39/42 vs gemini_3_7_flash 39, gap 0; abstention 42/42 vs fable 42, gap 0; coding 36/42 vs grok_4_3 27, gap 9/42 = 0.2143.

Stable by bucket: knowledge 40/42 vs opus 40, gap 0; math 42/42 gap 0; instruction 37/42 vs gemini_3_1_pro 36, gap 1/42; extraction 42/42 gap 0; toolcall 39/42 gap 0; abstention 42/42 gap 0; coding 32/42 vs fable 25, gap 7/42 = 0.1667.

### Language-level gate

| rule | lang | oracle | best_single | gap | gap rate | > 5.37% flip floor? |
|---|---|---:|---|---:|---:|---|
| naive A | ko | 94/98 | opus 84/98 | 10 | 10.20% | yes |
| naive A | en | 94/98 | sonnet 85/98 | 9 | 9.18% | yes |
| naive A | hi | 92/98 | fable 85/98 | 7 | 7.14% | yes |
| stable | ko | 92/98 | opus 83/98 | 9 | 9.18% | yes |
| stable | en | 92/98 | sol 82/98 | 10 | 10.20% | yes |
| stable | hi | 90/98 | gemini_3_7_flash 83/98 | 7 | 7.14% | yes |

Every language-level gap exceeds the measured **221/4116 = 5.37%** cell-flip
floor (and the earlier 9/294 = 3.06% floor). best_single changes in all three
languages. Language routing therefore has signal, but its global gain is
modest: choosing a model by language captures **5 cells** on naive A
(249→254) and **3 cells** on stable (245→248).

### Within-/between-bucket decomposition by language

“Within” sums oracle−best over seven bucket×language slices. “Between” is
the language-level gap minus within; it is what a task-type selector captures
inside that language.

| rule | lang | overall gap | within bucket | between bucket | coding within | other 6 within |
|---|---|---:|---:|---:|---:|---:|
| naive A | ko | 10 | 5 | 5 | 3 | 2 |
| naive A | en | 9 | 2 | 7 | 2 | 0 |
| naive A | hi | 7 | 2 | 5 | 1 | 1 |
| stable | ko | 9 | 3 | 6 | 2 | 1 |
| stable | en | 10 | 2 | 8 | 2 | 0 |
| stable | hi | 7 | 1 | 6 | 1 | 0 |

Detailed nonzero within cells:

- naive ko: knowledge 1, instruction 1, coding 3; en: coding 2;
  hi: instruction 1, coding 1.
- stable ko: instruction 1, coding 2; en: coding 2; hi: coding 1.

Coding concentration has the **same direction in all three languages**:
coding is the only or dominant within-bucket residual everywhere. Magnitude
is uneven (`ko/en/hi` naive 3/2/1; stable 2/2/1), so do not claim equality.
Every non-coding per-language residual is 0–2 cells, below the jitter floor.

Across languages, allowing both task type and language selects 271/280 naive
oracle cells (residual 9) versus 268/280 for task type alone (residual 12).
Stable: 268/274 (residual 6) versus 266/274 (residual 8). Thus language adds
3 naive cells / 2 stable cells after task type; coding remains the learned
residual.

## Copy

```
replicate1 DONE 14/14  last-per-key 4116/4116  audit forbidden_hits=[] extra_keys=[]
infra A: 2  sol+luna coding:abc390_c ko sandbox_error attempt 3
infra B: 1  luna same cell  (sol B scored ok correct=0)
cap_hit A 43  B 50
parse_failed A 56  B 56  composition moved (not the same 56)
  A: grok_4_6 17 grok_4_3 16 gemini_3_7_flash 6 fable 4 luna 3 sol 2 terra 2 sonnet 2 opus 1 g31 1 ds_pro 1 ds_flash 1 kimi 0 qwen 0
  B: grok_4_6 15 grok_4_3 13 fable 7 gemini_3_7_flash 6 luna 4 kimi 4 g31 2 terra 2 opus 1 sol 1 qwen 1 sonnet 0 ds_pro 0 ds_flash 0
billed A 51.557488  B 49.591932  d=-3.81%  (Pareto cost-axis noise floor)
cost-null both: opus toolcall:parallel_multiple_139 en  no catalog impute
  FINAL: exclude that cell, keep opus Pareto point, report cost on 293 billed cells
stable cap-excl n: union of unusable A∪B (qwen cap 12∪13=14 → n=280)
stable rewards determinism: gemini_3_7_flash 0 flips can win stable×parse-excl; sonnet/flash lose 16 on 1->0

gemini_3_7_flash correct-bit 0 flips, but not A copied: identical rows 0/294, same latency_ms 0/294
  latency sum 1692059 vs 1916468; billed 0.468923 vs 0.469771; completion_tok 237769 vs 238221
gemini_3_1_pro identical rows 0/294, same latency 0/294, billed 7.109740 vs 6.938848

jitter A vs B scored-correct flips 221/4116  (115 1->0, 106 0->1)
  bucket: coding 73 knowledge 49 toolcall 41 extraction 21 abstention 20 instruction 16 math 1
temp0/seed42 not bit-identical. recap smoke >=9/294 1->0. grok replay ~11/66.
gaps < 9/294=0.0306 are not a router signal.

VARIANTS  (main=stable all-cells; keep all seven)
naive A all-cells     oracle 280/294=0.9524  best fable=opus 249/294=0.8469  gap 0.1054
naive B all-cells     oracle 277/294=0.9422  best opus 252/294=0.8571       gap 0.0850
MAIN stable all-cells oracle 274/294=0.9320  best opus 245/294=0.8333       gap 0.0986
naive A cap-excluded  oracle 280/294=0.9524  best qwen 248/282=0.8794       gap 0.0729
stable cap-excluded   oracle 274/294=0.9320  best qwen 238/280=0.8500       gap 0.0820
naive A parse-excl    oracle 280/294=0.9524  best fable 249/290=0.8586      gap 0.0938
stable parse-excl     oracle 274/294=0.9320  best gemini_3_7_flash 244/288=0.8472  gap 0.0848
cap_hit exclusion = our max_tokens design (e5932f3). parse_failed exclusion = model contract miss (aa30e9b).
oracle unchanged by either exclusion. grok does not become best_single under parse-excl.
all: oracle > best_single, gap 0.073-0.105 > 0.0306
split: who is best_single

DECISION
  naive A gap 31 = within-bucket 12 + between-bucket 19
  within 12 = coding 9 + other six buckets 3
  task-type classifier captures 19/31=61.3% for free
  learned-routing residual is materially coding only; do NOT write “router is useful”

LANGUAGE
  naive: ko 94 vs opus 84 gap10; en 94 vs sonnet 85 gap9; hi 92 vs fable 85 gap7
  stable: ko 92 vs opus 83 gap9; en 92 vs sol 82 gap10; hi 90 vs g37flash 83 gap7
  all language gaps exceed 5.37% flip floor; best_single changes by language
  within/between naive: ko 5/5 (coding3), en 2/7 (coding2), hi 2/5 (coding1)
  within/between stable: ko 3/6 (coding2), en 2/8 (coding2), hi 1/6 (coding1)
  coding is dominant in all languages, but magnitude is not equal

infra-2 drop item coding:abc390_c ko
  fable A and opus A both correct=1 on that item → both 248/293=0.8464
  naive 279/293 vs tied 248/293 gap 0.1058
  stable 273/293 vs opus 244/293 gap 0.0990
  not sensitive

naive bucket gap: knowledge 1/42  math 0  instruction 2/42  extraction 0  toolcall 0  abstention 0  coding 9/42=0.2143
stable bucket gap: knowledge 0  math 0  instruction 1/42  extraction 0  toolcall 0  abstention 0  coding 7/42=0.1667
coding is the only bucket clearly above the 9/294 floor
```
