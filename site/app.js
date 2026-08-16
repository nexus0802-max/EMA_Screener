const state = { candidates: [], metadata: {} };

const yen = new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 2 });

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderRows() {
  const query = document.querySelector("#search").value.trim().toLowerCase();
  const weekly = document.querySelector("#weekly-filter").value;
  const rows = state.candidates.filter((row) => {
    const matchesQuery = !query || `${row.code} ${row.company_name}`.toLowerCase().includes(query);
    const matchesWeekly = weekly === "ALL" || row.weekly_status === weekly;
    return matchesQuery && matchesWeekly;
  });

  document.querySelector("#ranking-body").innerHTML = rows.map((row) => `
    <tr>
      <td class="rank">${row.rank}</td>
      <td class="code">${escapeHtml(row.code)}</td>
      <td>${escapeHtml(row.company_name)}</td>
      <td class="number">¥${yen.format(row.close)}</td>
      <td class="number momentum ${row.momentum63_pct >= 0 ? "positive" : "negative"}">${row.momentum63_pct >= 0 ? "+" : ""}${row.momentum63_pct.toFixed(2)}%</td>
      <td><span class="badge ${row.weekly_status === "OK" ? "ok" : "ng"}">${row.weekly_status}</span></td>
      <td><span class="action">翌営業日始値</span></td>
      <td><a class="chart" href="${escapeHtml(row.chart_url)}" target="_blank" rel="noopener">開く ↗</a></td>
    </tr>`).join("");
  document.querySelector("#empty").hidden = rows.length !== 0;
}

function applyPayload(payload) {
  state.metadata = payload.metadata;
  state.candidates = payload.candidates;

  const m = state.metadata;
  document.querySelector("#candidate-count").textContent = `${m.candidate_count}銘柄`;
  document.querySelector("#weekly-ok-count").textContent = `${m.weekly_ok_count}銘柄`;
  document.querySelector("#fresh-count").textContent = `${m.fresh_count} / ${m.component_count}`;
  document.querySelector("#as-of-date").textContent = m.as_of_date;
  document.querySelector("#fetched-at").textContent = `最終更新：${m.fetched_at}`;
  document.querySelector("#status").textContent = `シグナル日 ${m.as_of_date}｜${m.rule}`;
  document.querySelector("#status").classList.add("ready");
  renderRows();
}

async function loadData() {
  try {
    const embedded = document.querySelector("#screener-data");
    if (embedded?.textContent.trim()) {
      applyPayload(JSON.parse(embedded.textContent));
      return;
    }
    const response = await fetch(`data.json?v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    applyPayload(await response.json());
  } catch (error) {
    document.querySelector("#status").textContent = `データを読み込めませんでした：${error.message}`;
    document.querySelector("#status").classList.add("error");
  }
}

function downloadCsv(event) {
  if (!state.candidates.length) return;
  event.preventDefault();
  const columns = Object.keys(state.candidates[0]);
  const quote = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
  const lines = [columns.map(quote).join(",")];
  state.candidates.forEach((row) => lines.push(columns.map((column) => quote(row[column])).join(",")));
  const blob = new Blob(["\ufeff", lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `EMA_signals_${state.metadata.as_of_date}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

document.querySelector("#search").addEventListener("input", renderRows);
document.querySelector("#weekly-filter").addEventListener("change", renderRows);
document.querySelector("#download-csv").addEventListener("click", downloadCsv);
loadData();
