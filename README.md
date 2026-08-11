# 📊 MECAT — Painel de Ausências e Atrasos

Sistema completo (ETL + GitHub Actions + Dashboard de Signage) para monitorar
solicitações de ausência, atraso e day off dos colaboradores, extraídas
automaticamente de e-mails salvos em PDF.

```
┌────────────┐     push PDF     ┌──────────────────┐     gera      ┌─────────────────────┐
│  dados/*.pdf│ ───────────────▶ │ GitHub Actions    │ ────────────▶ │ banco_ausencias.xlsx │
│  (você add) │                  │ process_data.py   │               │ dados.json           │
└────────────┘                  └──────────────────┘               └──────────┬──────────┘
                                                                                │
                                                                                ▼
                                                                  ┌─────────────────────────┐
                                                                  │ GitHub Pages (index.html)│
                                                                  │ Dashboard dark/signage    │
                                                                  └─────────────────────────┘
```

## 🗂️ Estrutura do repositório

```
.
├── dados/                          # 👉 Coloque aqui os PDFs dos e-mails de ausência
│   └── .gitkeep
├── database/
│   └── banco_ausencias.xlsx        # Banco mestre (gerado/atualizado automaticamente)
├── scripts/
│   └── process_data.py             # Pipeline de ETL (extração + parsing + dedup)
├── .github/workflows/
│   └── process_emails.yml          # Automação: roda o pipeline e publica no Pages
├── index.html                      # Dashboard (estrutura)
├── styles.css                      # Dashboard (tema dark/signage)
├── app.js                          # Dashboard (lógica, filtros, gráficos)
├── dados.json                      # Saída do pipeline, consumida pelo frontend
└── README.md
```

## 🚀 Como publicar

1. **Crie o repositório no GitHub** e suba todo este conteúdo (`git init`, `git add .`,
   `git commit -m "init"`, `git push`).

2. **Habilite o GitHub Pages via GitHub Actions**:
   `Settings → Pages → Source → GitHub Actions`.

3. **Garanta as permissões do workflow**:
   `Settings → Actions → General → Workflow permissions → "Read and write permissions"`.
   (necessário para o Actions conseguir commitar `banco_ausencias.xlsx` e `dados.json` de volta).

4. **Adicione um PDF de e-mail** na pasta `dados/` e faça o push:
   ```bash
   cp ~/Downloads/email-ausencia.pdf dados/
   git add dados/email-ausencia.pdf
   git commit -m "novo email de ausencia"
   git push
   ```
   Isso dispara o workflow `process_emails.yml`, que:
   - lê todos os PDFs em `dados/`;
   - extrai e classifica as ocorrências;
   - deduplica pelo hash `colaborador_data_turno`;
   - atualiza `database/banco_ausencias.xlsx` e `dados.json`;
   - faz commit dessas duas alterações de volta no repositório;
   - publica o dashboard atualizado no GitHub Pages.

5. Acesse o painel em `https://<seu-usuario>.github.io/<seu-repositorio>/`.

## 🖥️ Rodando localmente

**Pipeline (Python 3.10+):**
```bash
pip install pandas openpyxl pypdf pdfplumber
python scripts/process_data.py
```

**Dashboard (qualquer servidor estático, pois usa `fetch()`):**
```bash
python -m http.server 8000
# depois abra http://localhost:8000
```
> Abrir `index.html` direto no navegador (`file://`) não funciona, pois o `fetch("dados.json")`
> é bloqueado por CORS em `file://`. Sempre sirva por um servidor HTTP, mesmo local.

## ⚙️ Regras de negócio do parser (`scripts/process_data.py`)

- **Filtro temporal**: apenas ocorrências com data a partir de 1º de janeiro do ano corrente
  são consideradas (registros antigos são descartados).
- **Deduplicação**: cada ocorrência recebe um hash MD5 de `colaborador_data_turno`. Isso
  também resolve, de forma natural, o fato de e-mails em cadeia (forward/reply) repetirem o
  mesmo registro várias vezes no mesmo PDF — só a primeira ocorrência do hash é gravada.
- **Categorias automáticas**: `Consulta/Exame Médico`, `Motivo Pessoal/Familiar`,
  `Banco de Horas / Folga`, `Burocrático/Financeiro`, `Outros / Imprevistos` — atribuídas por
  palavras-chave no texto de cada ocorrência (ver `CATEGORIA_KEYWORDS` no script).
- **Comprovante**: marcado como `Sim` quando o texto menciona atestado/anexo sem negação
  próxima (`"não recebi atestado"` → `Não`); caso contrário `Não`.
- **Turno**: `Manhã`, `Tarde`, `Integral` (dia todo / não especificado) ou `Flexível/Horas`
  (uso de banco de horas).

⚠️ **Limitação conhecida**: o parser é baseado em regex sobre texto de e-mail em linguagem
natural, com um formato relativamente consistente (mas não rígido). Novos formatos de frase
muito diferentes dos observados podem não ser capturados — revise periodicamente
`database/banco_ausencias.xlsx` e ajuste os padrões em `scripts/process_data.py` conforme
necessário.

## 📊 Sobre o dashboard

- **Filtros dinâmicos**: Ano, Mês, Colaborador e Categoria — recalculados a partir dos dados
  carregados (não são fixos no HTML).
- **KPIs**: total de solicitações, colaboradores afetados, ausências por motivo médico e
  colaborador com mais registros — todos recalculados a cada mudança de filtro.
- **Gráfico de rosca**: distribuição por categoria, com percentual exato em cada fatia.
- **Gráfico de barras**: evolução mensal, sempre ordenado Jan → Dez.
- **Tabela**: últimas 30 solicitações (após filtro), com pílulas coloridas por categoria e
  indicador visual de comprovante.
- **Layout**: pensado para telas de signage (100vw × 100vh, sem rolagem vertical); em telas
  menores (`< 1100px`) o layout se adapta para navegação vertical normal.

## 🔧 Dependências do pipeline

`pandas`, `openpyxl`, `pypdf` (ou `pdfplumber`, usado preferencialmente se instalado).

## 🎨 Dependências do frontend (via CDN, sem build step)

`Chart.js 4.4.4` + `chartjs-plugin-datalabels 2.2.0`, fontes `Rajdhani` e `Chakra Petch`
(Google Fonts).
