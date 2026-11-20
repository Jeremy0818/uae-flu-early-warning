// Weekly Google Trends pull for the early-warning model.
//
// Google Trends has no open API, so this runs in your own browser:
//   1. Open https://trends.google.com/trends/explore (no sign-in needed).
//   2. Open DevTools (F12) > Console, paste this whole file, press Enter.
//   3. It saves trends_pull_YYYY-MM-DD.json to your Downloads folder (about 15 s).
//   4. python scripts/refresh.py --trends <that file>
//
// It requests exactly the same comparisons as the original pull (influenza topics for UAE and
// Abu Dhabi, search terms for UAE, influenza topic across emirates) and adds a checksum per column
// so the import can verify nothing was lost in transit.
(async () => {
  const strip = t => JSON.parse(t.slice(t.indexOf("{")));
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const TIME = "today 5-y";
  const TOPICS = ["/m/0cycc", "/m/0cjf0", "/m/0n073", "/m/01b_21"];
  const TOPIC_LABELS = ["/m/0cycc Influenza", "/m/0cjf0 Fever", "/m/0n073 Common cold", "/m/01b_21 Cough"];
  const TERMS = ["flu", "انفلونزا", "fever", "cough medicine", "زكام"];

  async function pull(items) {           // items: [{keyword, geo}]
    const req = { comparisonItem: items.map(i => ({ ...i, time: TIME })), category: 0, property: "" };
    const r1 = await fetch("/trends/api/explore?hl=en-US&tz=-240&req=" + encodeURIComponent(JSON.stringify(req)));
    if (!r1.ok) throw new Error("explore " + r1.status + " (wait a minute and try again)");
    const w = strip(await r1.text()).widgets.find(w => w.id === "TIMESERIES");
    const r2 = await fetch("/trends/api/widgetdata/multiline?hl=en-US&tz=-240&req=" +
      encodeURIComponent(JSON.stringify(w.request)) + "&token=" + w.token);
    if (!r2.ok) throw new Error("multiline " + r2.status);
    const rows = strip(await r2.text()).default.timelineData.map(p => ({ t: +p.time, v: p.value, partial: !!p.isPartial }));
    const gaps = new Set(rows.slice(1).map((r, i) => r.t - rows[i].t));
    if (gaps.size !== 1 || !gaps.has(604800)) throw new Error("expected weekly rows, got gaps " + [...gaps]);
    await sleep(2500);
    return rows;
  }

  const today = new Date().toISOString().slice(0, 10);
  function toText(title, cols, rows, extra = []) {
    const n = cols.length;
    const sum = Array.from({ length: n }, (_, j) => rows.reduce((a, r) => a + r.v[j], 0));
    const wsum = Array.from({ length: n }, (_, j) => rows.reduce((a, r, i) => a + (i + 1) * r.v[j], 0));
    const last = rows.at(-1).partial ? "Last row partial." : "Last row complete.";
    const toks = rows.map(r => r.v.join("."));
    const body = [];
    for (let i = 0; i < toks.length; i += 20) body.push(toks.slice(i, i + 20).join(" "));
    return [
      `# Google Trends multiline, ${title}, time=${TIME}, pulled ${today}. start_unix=${rows[0].t} step=604800 (week starts Sunday UTC). ${last}`,
      ...extra,
      `# checksum sum=${sum.join(",")} wsum=${wsum.join(",")}`,
      `# cols: ${cols.join("|")}`,
      ...body,
    ].join("\n") + "\n";
  }

  const files = {};
  console.log("Pulling 5 comparisons from Google Trends…");
  files["topics_AE"] = toText("geo=AE", TOPIC_LABELS, await pull(TOPICS.map(k => ({ keyword: k, geo: "AE" }))));
  files["topics_AE-AZ"] = toText("geo=AE-AZ (Abu Dhabi)", TOPIC_LABELS, await pull(TOPICS.map(k => ({ keyword: k, geo: "AE-AZ" }))));
  files["terms_AE"] = toText("geo=AE", TERMS, await pull(TERMS.map(k => ({ keyword: k, geo: "AE" }))));
  const EM = ["AE-AZ", "AE-DU", "AE-SH", "AE-AJ", "AE-RK"];
  const a = await pull(EM.map(g => ({ keyword: "/m/0cycc", geo: g })));
  const b = await pull(["AE-AZ", "AE-UQ", "AE-FU"].map(g => ({ keyword: "/m/0cycc", geo: g })));
  const zeros = (rows, j) => rows.filter(r => r.v[j] === 0).length;
  files["emirates_AE"] = toText("topic /m/0cycc Influenza, one comparison across emirates (shared scale)", EM, a, [
    `# zero-week counts in the same pull: ${EM.map((g, j) => `${g} ${zeros(a, j)}`).join(", ")}; ` +
    `separate pull [AE-AZ, AE-UQ, AE-FU]: AE-UQ ${zeros(b, 1)}, AE-FU ${zeros(b, 2)} of ${b.length}`,
  ]);

  const blob = new Blob([JSON.stringify({ pulled: today, files }, null, 1)], { type: "application/json" });
  const link = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: `trends_pull_${today}.json` });
  document.body.appendChild(link); link.click(); link.remove();
  console.log(`Saved trends_pull_${today}.json. Next: python scripts/refresh.py --trends <path to that file>`);
})().catch(e => console.error("Trends pull failed:", e.message));
