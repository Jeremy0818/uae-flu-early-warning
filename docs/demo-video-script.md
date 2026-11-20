# Demo video script: Respiratory Early Warning (about 2 min 45 s)

Target: about 380 spoken words at a calm 140–150 words a minute. Every number below comes from the dashboard, so you can say it while it is on screen.

## Before you record

1. Use the live dashboard at https://uae-flu-ewarn.web.app. To record offline instead, run `python -m http.server 8765 --directory dashboard` and swap `https://uae-flu-ewarn.web.app/` for `http://localhost:8765/` in the links below.
2. Set the browser window to 1920×1080 with browser zoom at 100%. Close other tabs and turn off notifications.
3. Open these deep links in separate tabs, in order. Each one loads the dashboard in exactly the state you need, so you don't have to fiddle with the slider on camera:

| Tab | Link | Shows |
|---|---|---|
| A | `https://uae-flu-ewarn.web.app/#role=surv` | Latest week (9 Nov 2026), surveillance view |
| B | `https://uae-flu-ewarn.web.app/#week=2023-09-18&role=surv` | Replay week, 18 Sep 2023 |
| C | `https://uae-flu-ewarn.web.app/#tab=backtest` | Back-test evidence |
| D | `https://uae-flu-ewarn.web.app/#tab=governance` | Governance and method |

4. Record with Windows Game Bar (Win+Alt+R), OBS or Clipchamp. Record each scene as its own clip; that makes them easier to retake.
5. Optional: the deck cover (slide 1) works as a 3-second title card at the start and the ask slide (slide 12, with the live demo link) as the end card.

## Scenes

### 1 · Hook (0:00–0:15) · deck slide 1, or Tab A header
**Say:** “Every autumn, influenza hits the UAE, and every autumn our health system finds out from lab results that are about two weeks old. We built an early-warning system that estimates where flu is *this* week, explains why, and tells each team what to do.”

**On-screen caption:** See the flu wave before the lab confirms it

### 2 · The live view (0:15–0:45) · Tab A
**Do:** Hover over the alert card, then slowly over the three “Why” bars, then the actions column.

**Say:** “This is the live view for the week of 9 November 2026. The status is WARNING. We estimate 20.7 percent of flu tests are positive this week, and there is a 79 percent chance positivity is above the epidemic threshold. Every number is explained. The latest lab result anchors the estimate, and search interest and the seasonal pattern adjust it. You can see each signal’s effect in percentage points. On the right are proportionate actions for the person responsible.”

**Caption:** Lab-anchored · search and season adjust · every number explained

### 3 · Role-based views (0:45–1:00) · Tab A
**Do:** Change “View as” to *Hospital & clinic operations*, then to *Schools & community*.

**Say:** “Each role sees only what it needs. Hospital operations get the level, the estimate and a surge plan. Schools and the community get plain advice, with no counts and no probabilities. Weeks with small specimen numbers are suppressed outside the surveillance team.”

**Caption:** Role-based views · small-cell suppression

### 4 · Replay: autumn 2023 (1:00–1:40) · Tab B
**Do:**
1. Pause on the WARNING card, then point at the “Search interest” driver.
2. Tick **Show what happened next**. The lab line continues dashed and the grey wave band appears.
3. Tick **Simulate search-feed outage**. The status drops to WATCH and the degraded-mode banner appears.

**Say:** “Now let’s replay a real season using only the data that existed at the time. On 18 September 2023, the latest lab result was just 8.3 percent, well below the threshold. But influenza searches had jumped 39 percent in two weeks, and the system issued a WARNING. *(tick hindsight)* Here’s what happened next. The wave started on 9 October and peaked at 27 percent. A rule that waits for lab data could first have fired on 23 October, five weeks after our warning. *(tick outage)* And if the search feed fails, the system says so, switches to degraded mode and drops to WATCH. It degrades; it doesn’t guess.”

**Caption:** 18 Sep: WARNING · lab-only rule: 23 Oct · fails safe

### 5 · The evidence (1:40–2:15) · Tab C
**Do:** Pause on the four tiles. Scroll to the head-to-head table, then to the “Fair test” and “Calibration” tables.

**Say:** “We back-tested every week from 2022 to 2026, refitting the model each time on only the data available that week. It warned before lab confirmation for all five waves, with no false-alarm episodes, and flagged 95 percent of the weeks that turned out to be above threshold. We’re also honest about the limits. The UAE season is regular, so a simple calendar also catches autumn onsets. What it misses is the rest of the wave, and it can’t give you a level or a probability. Our probabilities are calibrated: weeks we gave 60 to 70 percent turned out positive 74 percent of the time.”

**Caption:** 5 of 5 waves · 0 false alarms · 95% of high weeks flagged · calibrated

### 6 · Governance (2:15–2:30) · Tab D
**Do:** Scroll slowly through the data sources, privacy controls and model card.

**Say:** “It uses only public, aggregated data, with no individual or disciplinary use, a human in the loop, and a full audit trail. The model is small and inspectable, and runs in seconds on a laptop.”

**Caption:** Aggregated data · human in the loop · auditable

### 7 · Close (2:30–2:45) · deck slide 11
**Say:** “Our ask is a twelve-week shadow pilot with the Department of Health surveillance team: their sentinel feed, no change to current practice, and a measured answer on how many weeks this gives your teams. Thank you.”

**Caption:** Ask: 12-week shadow pilot with DoH Abu Dhabi

## Word count and timing check

Spoken text comes to about 390 words, which is about 2 min 40 s at 145 wpm. If you run long, trim scene 3 first (it can be shown without narration) and then the second half of scene 5.

## Things not to say

- Don't say “predicts the future” or “predicts flu from Google searches.” Say “estimates this week before the lab confirms it.”
- Don't quote “+5 weeks” as a general lead time. Five weeks is the 2023 example; most of the general head start comes from seasonality.
- Don't call it a medical device or diagnostic.
