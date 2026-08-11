/* =====================================================================
   MECAT — Painel de Ausências — app.js
   Consome dados.json (gerado pelo pipeline Python), aplica filtros
   dinâmicos e renderiza KPIs, gráficos (Chart.js) e a tabela.
   ===================================================================== */

const MESES_ABREV = ["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"];

const CATEGORIA_PILL_CLASS = {
  "Consulta/Exame Médico": "pill-medico",
  "Motivo Pessoal/Familiar": "pill-pessoal",
  "Banco de Horas / Folga": "pill-banco",
  "Burocrático/Financeiro": "pill-financeiro",
  "Outros / Imprevistos": "pill-outros",
};

const CATEGORIA_COLOR = {
  "Consulta/Exame Médico": "#8b7bf7",
  "Motivo Pessoal/Familiar": "#f2b84b",
  "Banco de Horas / Folga": "#2bd9c9",
  "Burocrático/Financeiro": "#f2687a",
  "Outros / Imprevistos": "#7c8bab",
};

let ESTADO = {
  todas: [],       // todas as ocorrências carregadas do dados.json
  filtradas: [],    // após aplicar os filtros ativos
  chartCategoria: null,
  chartMensal: null,
};

// ---------------------------------------------------------------------
// Relógio em tempo real
// ---------------------------------------------------------------------
function iniciarRelogio() {
  const el = document.getElementById("clock");
  function tick() {
    const agora = new Date();
    el.textContent = agora.toLocaleTimeString("pt-BR", { hour12: false });
  }
  tick();
  setInterval(tick, 1000);
}

// ---------------------------------------------------------------------
// Carregamento dos dados
// ---------------------------------------------------------------------
async function carregarDados() {
  try {
    const resp = await fetch("dados.json", { cache: "no-store" });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const payload = await resp.json();
    ESTADO.todas = payload.ocorrencias || [];
    atualizarStatusPill(true, payload.gerado_em);
  } catch (err) {
    console.error("Falha ao carregar dados.json:", err);
    ESTADO.todas = [];
    atualizarStatusPill(false);
  }
}

function atualizarStatusPill(ok, geradoEm) {
  const pill = document.getElementById("status-pill");
  if (ok) {
    pill.innerHTML = `<span class="dot"></span> DADOS ATUALIZADOS`;
    pill.title = geradoEm ? `Última geração: ${new Date(geradoEm).toLocaleString("pt-BR")}` : "";
  } else {
    pill.innerHTML = `<span class="dot" style="background:#f2687a"></span> FALHA AO CARREGAR`;
  }
}

// ---------------------------------------------------------------------
// Popular selects de filtro dinamicamente a partir dos dados
// ---------------------------------------------------------------------
function popularFiltros() {
  const anos = [...new Set(ESTADO.todas.map(o => o.data_ausencia.slice(0, 4)))].sort();
  const colaboradores = [...new Set(ESTADO.todas.map(o => o.colaborador))].sort();
  const categorias = [...new Set(ESTADO.todas.map(o => o.categoria))].sort();

  preencherSelect("f-ano", ["Todos", ...anos]);
  preencherSelect("f-mes", ["Todos", ...MESES_ABREV]);
  preencherSelect("f-colaborador", ["Todos", ...colaboradores]);
  preencherSelect("f-categoria", ["Todas", ...categorias]);

  ["f-ano", "f-mes", "f-colaborador", "f-categoria"].forEach(id => {
    document.getElementById(id).addEventListener("change", aplicarFiltros);
  });
  document.getElementById("f-reset").addEventListener("click", () => {
    document.getElementById("f-ano").value = "Todos";
    document.getElementById("f-mes").value = "Todos";
    document.getElementById("f-colaborador").value = "Todos";
    document.getElementById("f-categoria").value = "Todas";
    aplicarFiltros();
  });
}

function preencherSelect(id, opcoes) {
  const select = document.getElementById(id);
  select.innerHTML = "";
  opcoes.forEach(op => {
    const opt = document.createElement("option");
    opt.value = op;
    opt.textContent = op;
    select.appendChild(opt);
  });
}

// ---------------------------------------------------------------------
// Filtro
// ---------------------------------------------------------------------
function aplicarFiltros() {
  const ano = document.getElementById("f-ano").value;
  const mes = document.getElementById("f-mes").value;
  const colaborador = document.getElementById("f-colaborador").value;
  const categoria = document.getElementById("f-categoria").value;

  ESTADO.filtradas = ESTADO.todas.filter(o => {
    const data = new Date(o.data_ausencia + "T00:00:00");
    const okAno = ano === "Todos" || o.data_ausencia.slice(0, 4) === ano;
    const okMes = mes === "Todos" || MESES_ABREV[data.getMonth()] === mes;
    const okColab = colaborador === "Todos" || o.colaborador === colaborador;
    const okCat = categoria === "Todas" || o.categoria === categoria;
    return okAno && okMes && okColab && okCat;
  });

  renderizarTudo();
}

// ---------------------------------------------------------------------
// KPIs
// ---------------------------------------------------------------------
function renderizarKPIs() {
  const dados = ESTADO.filtradas;

  document.getElementById("kpi-total").textContent = dados.length;

  const colaboradoresUnicos = new Set(dados.map(o => o.colaborador));
  document.getElementById("kpi-colaboradores").textContent = colaboradoresUnicos.size;

  const medicos = dados.filter(o => o.categoria === "Consulta/Exame Médico").length;
  document.getElementById("kpi-medico").textContent = medicos;

  const contagem = {};
  dados.forEach(o => { contagem[o.colaborador] = (contagem[o.colaborador] || 0) + 1; });
  let topNome = "—", topQtd = 0;
  Object.entries(contagem).forEach(([nome, qtd]) => {
    if (qtd > topQtd) { topNome = nome; topQtd = qtd; }
  });
  document.getElementById("kpi-top-nome").textContent = topNome;
  document.getElementById("kpi-top-qtd").textContent = topQtd;
}

// ---------------------------------------------------------------------
// Gráfico de Rosca — Categoria
// ---------------------------------------------------------------------
function renderizarGraficoCategoria() {
  const dados = ESTADO.filtradas;
  const contagem = {};
  dados.forEach(o => { contagem[o.categoria] = (contagem[o.categoria] || 0) + 1; });

  const labels = Object.keys(contagem);
  const valores = Object.values(contagem);
  const cores = labels.map(l => CATEGORIA_COLOR[l] || "#7c8bab");

  const ctx = document.getElementById("chart-categoria").getContext("2d");

  if (ESTADO.chartCategoria) ESTADO.chartCategoria.destroy();

  ESTADO.chartCategoria = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels,
      datasets: [{
        data: valores,
        backgroundColor: cores,
        borderColor: "#0e1626",
        borderWidth: 3,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: "62%",
      plugins: {
        legend: {
          position: "bottom",
          labels: {
            color: "#7c8bab",
            font: { family: "'Chakra Petch', monospace", size: 11 },
            boxWidth: 10,
            padding: 10,
          },
        },
        datalabels: {
          color: "#ffffff",
          font: { weight: "bold", size: 13, family: "'Chakra Petch', monospace" },
          formatter: (value, ctx) => {
            const total = ctx.chart.data.datasets[0].data.reduce((a, b) => a + b, 0);
            if (!total) return "";
            const pct = (value / total) * 100;
            return pct.toFixed(0) + "%";
          },
        },
      },
    },
    plugins: [ChartDataLabels],
  });
}

// ---------------------------------------------------------------------
// Gráfico de Barras — Evolução Mensal (ordem cronológica fixa Jan..Dez)
// ---------------------------------------------------------------------
function renderizarGraficoMensal() {
  const dados = ESTADO.filtradas;
  const contagemPorMes = new Array(12).fill(0);

  dados.forEach(o => {
    const data = new Date(o.data_ausencia + "T00:00:00");
    contagemPorMes[data.getMonth()] += 1;
  });

  const ctx = document.getElementById("chart-mensal").getContext("2d");

  if (ESTADO.chartMensal) ESTADO.chartMensal.destroy();

  ESTADO.chartMensal = new Chart(ctx, {
    type: "bar",
    data: {
      labels: MESES_ABREV,
      datasets: [{
        label: "Solicitações",
        data: contagemPorMes,
        backgroundColor: "rgba(43, 217, 201, 0.75)",
        hoverBackgroundColor: "#2bd9c9",
        borderRadius: 4,
        maxBarThickness: 34,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        datalabels: {
          anchor: "end",
          align: "top",
          color: "#7c8bab",
          font: { size: 10, family: "'Chakra Petch', monospace" },
          formatter: (v) => (v > 0 ? v : ""),
        },
      },
      scales: {
        x: {
          ticks: { color: "#7c8bab", font: { family: "'Chakra Petch', monospace", size: 11 } },
          grid: { color: "rgba(30,44,70,0.5)" },
        },
        y: {
          beginAtZero: true,
          ticks: { color: "#7c8bab", precision: 0, font: { family: "'Chakra Petch', monospace", size: 11 } },
          grid: { color: "rgba(30,44,70,0.5)" },
        },
      },
    },
    plugins: [ChartDataLabels],
  });
}

// ---------------------------------------------------------------------
// Tabela de últimas solicitações
// ---------------------------------------------------------------------
function renderizarTabela() {
  const corpo = document.getElementById("tabela-body");
  corpo.innerHTML = "";

  const ordenadas = [...ESTADO.filtradas].sort((a, b) => b.data_ausencia.localeCompare(a.data_ausencia));
  const ultimas = ordenadas.slice(0, 30);

  if (ultimas.length === 0) {
    corpo.innerHTML = `<tr><td colspan="5" style="text-align:center;color:#4f5f80;padding:20px;">
      Nenhum registro encontrado para os filtros selecionados.</td></tr>`;
    return;
  }

  ultimas.forEach(o => {
    const tr = document.createElement("tr");
    const dataFmt = new Date(o.data_ausencia + "T00:00:00").toLocaleDateString("pt-BR");
    const pillClass = CATEGORIA_PILL_CLASS[o.categoria] || "pill-outros";
    const comprovanteOk = String(o.comprovante).toLowerCase() === "sim";
    const comprovanteHtml = comprovanteOk
      ? `<span class="comprovante-ok">✔ Sim</span>`
      : `<span class="comprovante-no">✖ Não</span>`;

    tr.innerHTML = `
      <td>${dataFmt}</td>
      <td>${o.colaborador}</td>
      <td>${o.turno}</td>
      <td><span class="pill ${pillClass}">${o.categoria}</span></td>
      <td>${comprovanteHtml}</td>
    `;
    corpo.appendChild(tr);
  });
}

// ---------------------------------------------------------------------
// Orquestração
// ---------------------------------------------------------------------
function renderizarTudo() {
  renderizarKPIs();
  renderizarGraficoCategoria();
  renderizarGraficoMensal();
  renderizarTabela();
}

async function iniciar() {
  iniciarRelogio();
  await carregarDados();
  popularFiltros();
  // Seleciona "Todos" por padrão em todos os filtros
  ESTADO.filtradas = [...ESTADO.todas];
  renderizarTudo();
}

document.addEventListener("DOMContentLoaded", iniciar);
