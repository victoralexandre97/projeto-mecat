"""
process_data.py
=================
Pipeline ETL do Dashboard de Ausências (Grupo MECAT).

O que este script faz:
1. Lê todos os PDFs em `dados/` (e-mails de solicitação de ausência impressos em PDF).
2. Extrai o texto puro de cada PDF (pdfplumber, com fallback para pypdf).
3. Usa regras/regex para identificar cada ocorrência de ausência/atraso/day off dentro do texto
   (mesmo quando o mesmo registro aparece repetido várias vezes por causa do histórico de
   e-mails encaminhados/respondidos em cadeia — isso é tratado na deduplicação).
4. Classifica cada ocorrência em uma categoria de negócio.
5. Gera um hash único por registro (colaborador + data + turno) para deduplicação.
6. Persiste o resultado em `database/banco_ausencias.xlsx` (só adiciona o que for novo).
7. Exporta `dados.json` na raiz do repositório, para o frontend consumir.

Regra de negócio crítica:
- Somente ocorrências com data a partir de 1º de janeiro do ano corrente são consideradas.
  Registros de anos anteriores são descartados silenciosamente (mas contabilizados no log).

Uso:
    python scripts/process_data.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path

import pandas as pd

# --------------------------------------------------------------------------------------
# Extração de texto do PDF (tenta pdfplumber; se não disponível, cai para pypdf)
# --------------------------------------------------------------------------------------
def extract_text_from_pdf(pdf_path: Path) -> str:
    try:
        import pdfplumber  # type: ignore

        text_parts = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text_parts.append(page.extract_text() or "")
        return "\n".join(text_parts)
    except ImportError:
        pass

    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(pdf_path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except ImportError:
        raise RuntimeError(
            "Nenhuma biblioteca de leitura de PDF disponível. "
            "Instale 'pdfplumber' ou 'pypdf' (pip install pdfplumber pypdf)."
        )


# --------------------------------------------------------------------------------------
# Estrutura de dados de uma ocorrência
# --------------------------------------------------------------------------------------
@dataclass
class Ocorrencia:
    hash_id: str
    colaborador: str
    data_ausencia: str  # ISO YYYY-MM-DD
    turno: str
    motivo_original: str
    categoria: str
    comprovante: str  # "Sim" / "Não"
    arquivo_origem: str


# --------------------------------------------------------------------------------------
# Regras de classificação (Categoria) — ordem importa: primeira regra que casar vence.
# --------------------------------------------------------------------------------------
CATEGORIA_KEYWORDS = [
    ("Consulta/Exame Médico", [
        "médic", "medic", "dentist", "raio x", "raio-x", "ortopedista",
        "oftalmolog", "cirurgia", "exame", "consulta", "hospital",
    ]),
    ("Banco de Horas / Folga", [
        "banco de horas", "day off", "banco positivo", "saldo positivo",
    ]),
    ("Burocrático/Financeiro", [
        "banco ", "pensão", "documento", "inss", "cartório", "financeir",
    ]),
    ("Motivo Pessoal/Familiar", [
        "problema pessoal", "filho", "filha", "colégio", "escola", "família",
        "familia", "imprevisto pessoal", "imprevisto familiar", "esposa", "esposo",
    ]),
    ("Outros / Imprevistos", [
        "falha mecânica", "falha mecanica", "oficina", "carro", "imprevisto",
    ]),
]


def classificar_categoria(texto: str) -> str:
    texto_lower = texto.lower()
    for categoria, palavras in CATEGORIA_KEYWORDS:
        if any(p in texto_lower for p in palavras):
            return categoria
    return "Outros / Imprevistos"


def detectar_comprovante(texto: str) -> str:
    """Retorna 'Sim' se houver menção a atestado/anexo sem negação próxima; caso
    contrário 'Não'."""
    texto_lower = texto.lower()
    termos_comprovante = ["atestado", "anexa", "anexo", "solicitação anexa"]
    if not any(t in texto_lower for t in termos_comprovante):
        return "Não"
    # Verifica negação próxima (ex.: "não recebi atestado", "sem atestado")
    negacoes = re.findall(r"(não\s+\w*\s*(atestado|anexo|anexa)|sem\s+atestado|sem\s+anexo)", texto_lower)
    if negacoes:
        return "Não"
    return "Sim"


def detectar_turno(texto: str) -> str:
    texto_lower = texto.lower()
    if "day off" in texto_lower:
        return "Integral"
    if "período da manhã" in texto_lower or "periodo da manha" in texto_lower:
        return "Manhã"
    if "período da tarde" in texto_lower or "periodo da tarde" in texto_lower:
        return "Tarde"
    if "banco de horas" in texto_lower or "banco positiv" in texto_lower:
        return "Flexível/Horas"
    return "Integral"


def normalizar_data(dia_str: str, ano_referencia: int) -> str | None:
    """Converte 'DD/MM/YY' ou 'DD/MM' em 'YYYY-MM-DD'. Se o ano não vier na string,
    assume o ano corrente (ano_referencia)."""
    partes = dia_str.strip().split("/")
    try:
        dia = int(partes[0])
        mes = int(partes[1])
        if len(partes) == 3:
            ano_raw = partes[2]
            ano = int(ano_raw)
            if ano < 100:
                ano += 2000
        else:
            ano = ano_referencia
        return date(ano, mes, dia).isoformat()
    except (ValueError, IndexError):
        return None


# --------------------------------------------------------------------------------------
# Parser principal: varre o texto do PDF em busca de blocos de ocorrência
# --------------------------------------------------------------------------------------
# Um "bloco" começa em uma linha tipo "- Nome – Informou ..." ou
# "- Nome – Day Off planejado ..." e vai até a próxima linha que comece um novo bloco
# (outro "- Nome –") ou até o fim do parágrafo.
BLOCO_INICIO_RE = re.compile(
    r"^\s*-\s*(?P<nome>[A-ZÀ-Ýa-zà-ÿ][\wÀ-ÿ'\.]*(?:\s+[A-ZÀ-Ýa-zà-ÿ][\wÀ-ÿ'\.]*){0,2})\s*[-–]\s*"
    r"(?P<resto>(Informou|Day Off).+)$",
    re.MULTILINE,
)

DATA_RE = re.compile(r"dia\s+(\d{1,2}/\d{1,2}(?:/\d{2,4})?)", re.IGNORECASE)
DATA_FICANDO_RE = re.compile(r"ficando\s+para\s+o\s+dia\s+(\d{1,2}/\d{1,2}(?:/\d{2,4})?)", re.IGNORECASE)

# Padrão alternativo de Day Off que não vem em formato de bullet "- Nome – ...",
# e sim como parágrafo corrido: "... Day Off planejado referente ao colaborador
# <Nome> do setor de <Setor>, ficando para o dia DD/MM."
DAYOFF_PARAGRAFO_RE = re.compile(
    r"Day\s*Off\s+planejado\s+referente\s+ao\s+colaborador\s+(?P<nome>[A-ZÀ-Ýa-zà-ÿ][\wÀ-ÿ'\.]*)"
    r".{0,80}?ficando\s+para\s+o\s+dia\s+(?P<data>\d{1,2}/\d{1,2}(?:/\d{2,4})?)",
    re.IGNORECASE | re.DOTALL,
)

# Marcadores que indicam o FIM do conteúdo relevante de um bloco (assinatura de e-mail,
# cabeçalho de mensagem encaminhada/respondida, etc.). O bloco é cortado no primeiro que
# aparecer, o que evita "vazar" texto de blocos seguintes no histórico de e-mails em cadeia.
BLOCO_FIM_RE = re.compile(
    r"\n\s*(Atenciosamente|De:|Enviada em:|Para:|Assunto:|-{3,}\s*Mensagem|"
    r"\d{1,2}/\d{2}/\d{4},\s*\d{2}:\d{2}|https?://)",
    re.IGNORECASE,
)


def parse_text(texto: str, arquivo_origem: str, ano_referencia: int) -> list[Ocorrencia]:
    ocorrencias: list[Ocorrencia] = []

    # Junta linhas quebradas de um mesmo bloco em uma única string lógica, mas mantém
    # marcação de início de bloco através do regex acima aplicado sobre o texto bruto.
    matches = list(BLOCO_INICIO_RE.finditer(texto))

    for i, m in enumerate(matches):
        nome = m.group("nome").strip()
        inicio = m.start()
        limite_proximo_bloco = matches[i + 1].start() if i + 1 < len(matches) else min(len(texto), m.end() + 600)

        # Corta no primeiro marcador de fim de bloco (assinatura, cabeçalho de e-mail
        # encaminhado, etc.) dentro da janela até o próximo bloco — o que vier primeiro.
        janela = texto[inicio:limite_proximo_bloco]
        fim_match = BLOCO_FIM_RE.search(janela)
        fim = inicio + fim_match.start() if fim_match else limite_proximo_bloco
        bloco = texto[inicio:fim]

        # Nome não deve ser um cabeçalho de e-mail (De:, Para:, Assunto:, etc.)
        if nome.lower() in {"de", "para", "assunto", "cc", "enviada em"}:
            continue

        data_match = DATA_RE.search(bloco) or DATA_FICANDO_RE.search(bloco)
        if not data_match:
            continue

        data_iso = normalizar_data(data_match.group(1), ano_referencia)
        if not data_iso:
            continue

        # Filtro temporal: somente a partir de 1º de janeiro do ano corrente
        if date.fromisoformat(data_iso) < date(ano_referencia, 1, 1):
            continue

        turno = detectar_turno(bloco)
        categoria = classificar_categoria(bloco)
        comprovante = detectar_comprovante(bloco)
        motivo = re.sub(r"\s+", " ", bloco).strip()[:500]

        hash_id = hashlib.md5(f"{nome}_{data_iso}_{turno}".encode("utf-8")).hexdigest()

        ocorrencias.append(
            Ocorrencia(
                hash_id=hash_id,
                colaborador=nome,
                data_ausencia=data_iso,
                turno=turno,
                motivo_original=motivo,
                categoria=categoria,
                comprovante=comprovante,
                arquivo_origem=arquivo_origem,
            )
        )

    # Segunda passada: captura ocorrências de Day Off em formato de parágrafo (fora do
    # padrão de bullet), deduplicando pelo mesmo hash caso já tenha sido capturado acima.
    hashes_ja_vistos = {oc.hash_id for oc in ocorrencias}
    for m in DAYOFF_PARAGRAFO_RE.finditer(texto):
        nome = m.group("nome").strip()
        data_iso = normalizar_data(m.group("data"), ano_referencia)
        if not data_iso or date.fromisoformat(data_iso) < date(ano_referencia, 1, 1):
            continue
        turno = "Integral"
        hash_id = hashlib.md5(f"{nome}_{data_iso}_{turno}".encode("utf-8")).hexdigest()
        if hash_id in hashes_ja_vistos:
            continue
        hashes_ja_vistos.add(hash_id)
        trecho = re.sub(r"\s+", " ", m.group(0)).strip()[:500]
        ocorrencias.append(
            Ocorrencia(
                hash_id=hash_id,
                colaborador=nome,
                data_ausencia=data_iso,
                turno=turno,
                motivo_original=trecho,
                categoria="Banco de Horas / Folga",
                comprovante="Não",
                arquivo_origem=arquivo_origem,
            )
        )

    return ocorrencias


# --------------------------------------------------------------------------------------
# Persistência: Excel mestre (deduplicado) + JSON para o frontend
# --------------------------------------------------------------------------------------
EXCEL_COLUMNS = [
    "hash_id", "colaborador", "data_ausencia", "turno",
    "motivo_original", "categoria", "comprovante", "arquivo_origem",
]


def carregar_banco_existente(excel_path: Path) -> pd.DataFrame:
    if excel_path.exists():
        df = pd.read_excel(excel_path, dtype=str)
        for col in EXCEL_COLUMNS:
            if col not in df.columns:
                df[col] = ""
        return df[EXCEL_COLUMNS]
    return pd.DataFrame(columns=EXCEL_COLUMNS)


def ordenar_banco(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(by=["data_ausencia", "colaborador"]).reset_index(drop=True)


def salvar_banco(df: pd.DataFrame, excel_path: Path) -> None:
    excel_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(excel_path, index=False, sheet_name="Ausencias")


def exportar_json(df: pd.DataFrame, json_path: Path) -> None:
    registros = df.to_dict(orient="records")
    payload = {
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "total_registros": len(registros),
        "ocorrencias": registros,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------
def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    dados_dir = repo_root / "dados"
    excel_path = repo_root / "database" / "banco_ausencias.xlsx"
    json_path = repo_root / "dados.json"

    ano_referencia = datetime.now().year

    if not dados_dir.exists():
        print(f"[AVISO] Pasta '{dados_dir}' não existe. Nada para processar.")
        dados_dir.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(dados_dir.glob("*.pdf"))
    if not pdfs:
        print(f"[INFO] Nenhum PDF encontrado em '{dados_dir}'.")

    banco = carregar_banco_existente(excel_path)
    hashes_existentes = set(banco["hash_id"].tolist())

    novos_registros: list[dict] = []
    total_extraidas = 0
    total_descartadas_ano = 0

    for pdf_path in pdfs:
        print(f"[INFO] Lendo {pdf_path.name} ...")
        try:
            texto = extract_text_from_pdf(pdf_path)
        except Exception as exc:  # noqa: BLE001
            print(f"[ERRO] Falha ao ler {pdf_path.name}: {exc}")
            continue

        ocorrencias = parse_text(texto, pdf_path.name, ano_referencia)
        total_extraidas += len(ocorrencias)

        for oc in ocorrencias:
            if oc.hash_id in hashes_existentes:
                continue  # duplicata — já está no banco (ou repetida no thread)
            hashes_existentes.add(oc.hash_id)
            novos_registros.append(asdict(oc))

    if novos_registros:
        novo_df = pd.DataFrame(novos_registros)[EXCEL_COLUMNS]
        banco = pd.concat([banco, novo_df], ignore_index=True)
        banco = banco.drop_duplicates(subset=["hash_id"], keep="first")

    banco = ordenar_banco(banco)
    salvar_banco(banco, excel_path)
    exportar_json(banco, json_path)

    print("----------------------------------------------------")
    print(f"PDFs processados:           {len(pdfs)}")
    print(f"Ocorrências extraídas:      {total_extraidas}")
    print(f"Novos registros adicionados:{len(novos_registros)}")
    print(f"Total no banco após rodada: {len(banco)}")
    print(f"Excel salvo em:             {excel_path}")
    print(f"JSON exportado em:          {json_path}")
    print("----------------------------------------------------")


if __name__ == "__main__":
    sys.exit(main() or 0)
