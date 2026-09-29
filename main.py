import logging
import os
import re
from io import BytesIO

from pypdf import PdfReader
from supabase import create_client, Client


# ============================================================
# CONFIGURAZIONE
# ============================================================

logging.getLogger("pypdf").setLevel(logging.ERROR)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise ValueError(
        "Variabili SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY mancanti."
    )

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY
)

BUCKET_NAME = "documents"
DOCUMENTS_TABLE = "documents"
EVIDENCE_TABLE = "evidence"


# ============================================================
# VOCABOLARIO DOCUMENTARIO
# ============================================================
#
# Questo vocabolario serve esclusivamente a individuare
# passaggi potenzialmente rilevanti.
#
# NON identifica componenti definitivi.
# NON stabilisce equivalenze tra denominazioni.
# NON determina fasi storiche.
# ============================================================

EVIDENCE_VOCAB = {
    # Edifici / spazi
    "belvedere": "belvedere",
    "filanda": "filanda",
    "filanda reale": "filanda reale",
    "gran filanda": "gran filanda",
    "setificio": "setificio",
    "setificio di san leucio": "setificio di San Leucio",
    "opificio": "opificio",
    "opificio borbonico": "opificio borbonico",
    "fabbrica della seta": "fabbrica della seta",
    "salone": "salone",
    "salone reale": "salone reale",
    "salone del belvedere": "salone del belvedere",
    "gran salone": "gran salone",
    "sala del trono": "sala del trono",
    "residenza reale": "residenza reale",
    "appartamento del re": "appartamento del re",
    "stanze reali": "stanze reali",
    "alloggi degli operai": "alloggi degli operai",
    "quartiere san ferdinando": "quartiere San Ferdinando",

    # Struttura / architettura
    "volta": "volta",
    "volte": "volta",
    "volta a botte": "volta a botte",
    "volta a padiglione": "volta a padiglione",
    "arco": "arco",
    "archi": "arco",
    "muratura": "muratura",
    "muro": "muro",
    "mura": "muro",
    "pilastro": "pilastro",
    "pilastri": "pilastro",
    "colonna": "colonna",
    "colonne": "colonna",
    "scalinata": "scalinata",
    "scalone": "scalone",
    "scala": "scala",
    "portico": "portico",
    "porticato": "portico",
    "terrazza": "terrazza",
    "terrazzo": "terrazza",
    "facciata": "facciata",
    "prospetto": "prospetto",
    "copertura": "copertura",

    # Produzione / macchinari
    "trattaglio": "trattaglio",
    "trattagli": "trattaglio",
    "telaio": "telaio",
    "telai": "telaio",
    "trattura": "trattura",
    "tessitura": "tessitura",

    # Acqua / infrastrutture
    "fontana": "fontana",
    "fontane": "fontana",
    "vasca": "vasca",
    "vasche": "vasca",
    "acquedotto": "acquedotto",
    "acquedotto carolino": "Acquedotto Carolino",
    "bagno": "bagno",
    "bagno grande": "Bagno Grande",
    "canale": "canale",
    "condotto": "condotto",
    "cavedio": "cavedio",

    # Spazi esterni
    "cortile": "cortile",
    "giardino": "giardino",
    "strada": "strada",
    "piazza": "piazza",
}


# ============================================================
# INDICATORI DI TRASFORMAZIONE
# ============================================================

TRANSFORMATION_VOCAB = {
    "costruito": "construction",
    "costruita": "construction",
    "costruiti": "construction",
    "costruite": "construction",
    "costruzione": "construction",
    "edificato": "construction",
    "edificata": "construction",
    "realizzato": "construction",
    "realizzata": "construction",

    "ampliato": "enlargement",
    "ampliata": "enlargement",
    "ampliamento": "enlargement",
    "ingrandito": "enlargement",
    "ingrandita": "enlargement",

    "demolito": "demolition",
    "demolita": "demolition",
    "demolizione": "demolition",
    "abbattuto": "demolition",
    "abbattuta": "demolition",

    "trasformato": "transformation",
    "trasformata": "transformation",
    "trasformazione": "transformation",
    "modificato": "transformation",
    "modificata": "transformation",
    "modifica": "transformation",

    "ricostruito": "reconstruction",
    "ricostruita": "reconstruction",
    "ricostruzione": "reconstruction",

    "restaurato": "restoration",
    "restaurata": "restoration",
    "restauro": "restoration",

    "aggiunto": "addition",
    "aggiunta": "addition",
    "aggiunse": "addition",

    "soppresso": "removal",
    "soppressa": "removal",
}


# ============================================================
# FUNZIONI TESTUALI
# ============================================================

def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def split_sentences(text: str) -> list[str]:
    """
    Divide il testo in unità documentarie semplici.

    Non effettua interpretazione storica.
    """

    clean_text = normalize_text(text)

    if not clean_text:
        return []

    sentences = re.split(
        r"(?<=[.!?;])\s+(?=[A-ZÀ-ÖØ-Ý0-9])",
        clean_text
    )

    return [
        sentence.strip()
        for sentence in sentences
        if len(sentence.strip()) >= 20
    ]


def detect_elements(sentence: str) -> list[str]:
    """
    Individua termini documentari di interesse.

    Il risultato NON equivale a un componente validato.
    """

    text_lower = sentence.lower()
    found = []

    for term, label in EVIDENCE_VOCAB.items():
        if re.search(
            r"\b" + re.escape(term) + r"\b",
            text_lower
        ):
            found.append(label)

    return sorted(set(found))


def detect_transformation_type(sentence: str):
    """
    Individua esclusivamente indicatori linguistici espliciti
    di trasformazione.
    """

    text_lower = sentence.lower()

    for term, transformation_type in TRANSFORMATION_VOCAB.items():
        if re.search(
            r"\b" + re.escape(term) + r"\b",
            text_lower
        ):
            return transformation_type

    return None


def extract_years(sentence: str) -> list[int]:
    """
    Estrae anni espressamente presenti nel testo.
    """

    matches = re.findall(
        r"\b(1[5-9]\d{2}|20\d{2})\b",
        sentence
    )

    return sorted(set(int(year) for year in matches))


def get_temporal_information(sentence: str) -> dict:
    years = extract_years(sentence)

    if not years:
        return {
            "temporal_reference": None,
            "start_year": None,
            "end_year": None,
            "temporal_precision": None,
        }

    if len(years) == 1:
        return {
            "temporal_reference": str(years[0]),
            "start_year": years[0],
            "end_year": years[0],
            "temporal_precision": "explicit_year",
        }

    return {
        "temporal_reference": " - ".join(str(y) for y in years),
        "start_year": min(years),
        "end_year": max(years),
        "temporal_precision": "multiple_explicit_years",
    }


# ============================================================
# STORAGE
# ============================================================

def list_all_files_in_bucket(path: str = "") -> list[str]:
    """
    Recupera ricorsivamente tutti i file presenti
    nel bucket Supabase.
    """

    results = []

    items = supabase.storage.from_(BUCKET_NAME).list(path)

    for item in items:
        name = item.get("name")

        if not name:
            continue

        current_path = f"{path}/{name}" if path else name

        if item.get("id") is None:
            results.extend(
                list_all_files_in_bucket(current_path)
            )
        else:
            results.append(current_path)

    return results


# ============================================================
# COLLEGAMENTO DOCUMENT
# ============================================================

def find_document_id(file_path: str):
    """
    Collega il file dello Storage alla tabella documents.

    Prima prova file_path.
    Se non viene trovato, prova il solo nome del file
    attraverso title.
    """

    try:
        result = (
            supabase.table(DOCUMENTS_TABLE)
            .select("id")
            .eq("file_path", file_path)
            .limit(1)
            .execute()
        )

        if result.data:
            return result.data[0]["id"]

    except Exception:
        pass

    file_name = os.path.basename(file_path)

    try:
        result = (
            supabase.table(DOCUMENTS_TABLE)
            .select("id")
            .eq("title", file_name)
            .limit(1)
            .execute()
        )

        if result.data:
            return result.data[0]["id"]

    except Exception:
        pass

    return None


# ============================================================
# ESTRAZIONE EVIDENCE
# ============================================================

def extract_evidence_from_pdf(
    file_path: str,
    document_id: str
) -> list[dict]:

    file_bytes = (
        supabase.storage
        .from_(BUCKET_NAME)
        .download(file_path)
    )

    reader = PdfReader(BytesIO(file_bytes))

    evidence_items = []

    for page_index, page in enumerate(reader.pages):

        page_number = page_index + 1
        page_text = page.extract_text() or ""

        if not page_text.strip():

            print(
                f"   Pagina {page_number}: "
                "nessun testo nativo."
            )

            continue

        sentences = split_sentences(page_text)

        for sentence in sentences:

            elements = detect_elements(sentence)

            if not elements:
                continue

            temporal = get_temporal_information(sentence)

            transformation_type = (
                detect_transformation_type(sentence)
            )

            # Una frase = una evidence.
            #
            # Se nella stessa frase compaiono più elementi,
            # vengono conservati nello stesso campo.
            element_string = ", ".join(elements)

            evidence_items.append(
                {
                    "document_id": document_id,

                    "page_reference": str(page_number),

                    "source_excerpt": sentence,

                    # Non essendoci ancora un modello semantico
                    # che parafrasa in modo controllato,
                    # manteniamo l'informazione oggettiva
                    # aderente alla fonte.
                    "objective_information": sentence,

                    "element": element_string,

                    "transformation_type":
                        transformation_type,

                    "temporal_reference":
                        temporal["temporal_reference"],

                    "start_year":
                        temporal["start_year"],

                    "end_year":
                        temporal["end_year"],

                    "temporal_precision":
                        temporal["temporal_precision"],

                    # Non vengono inventate informazioni
                    # spaziali non espresse.
                    "spatial_information": None,
                    "spatial_relation": None,
                    "location_description": None,

                    # Separazione fondamentale:
                    # evidence != interpretazione != ipotesi
                    "interpretation": None,
                    "hypothesis": None,

                    "knowledge_status":
                        "documentary_evidence",

                    # Queste valutazioni devono essere
                    # proposte successivamente e validate.
                    "geometry_definable": None,
                    "usable_for_3d": None,

                    # Nessuna fase storica viene inferita
                    # durante l'estrazione documentaria.
                    "phase_suggestion": None,
                    "phase_reason": None,
                    "phase_confidence": None,
                    "phase_validated": False,

                    # La evidence entra sempre da validare.
                    "review_status": "to_review",
                }
            )

    return evidence_items


# ============================================================
# IDEMPOTENZA
# ============================================================

def evidence_already_exists(item: dict) -> bool:
    """
    Evita duplicati se GitHub Actions viene eseguito
    più volte sullo stesso documento.
    """

    query = (
        supabase.table(EVIDENCE_TABLE)
        .select("id")
        .eq("document_id", item["document_id"])
        .eq("page_reference", item["page_reference"])
        .eq("source_excerpt", item["source_excerpt"])
    )

    if item.get("element") is not None:
        query = query.eq(
            "element",
            item["element"]
        )

    result = query.limit(1).execute()

    return bool(result.data)


def save_evidence(items: list[dict]) -> tuple[int, int]:

    inserted = 0
    skipped = 0

    for item in items:

        if evidence_already_exists(item):
            skipped += 1
            continue

        supabase.table(EVIDENCE_TABLE).insert(
            item
        ).execute()

        inserted += 1

    return inserted, skipped


# ============================================================
# PROCESSO PRINCIPALE
# ============================================================

def process_documents():

    files = list_all_files_in_bucket()

    pdf_files = [
        path
        for path in files
        if path.lower().endswith(".pdf")
    ]

    if not pdf_files:
        print("Nessun PDF trovato nello Storage.")
        return

    print(
        f"Trovati {len(pdf_files)} PDF "
        f"nel bucket '{BUCKET_NAME}'."
    )

    for file_path in pdf_files:

        print("\n" + "=" * 80)
        print(f"FILE: {file_path}")
        print("=" * 80)

        try:

            document_id = find_document_id(
                file_path
            )

            if not document_id:

                print(
                    "   [SKIP] File non associato "
                    "a nessun record in documents."
                )

                continue

            print(
                f"   document_id = {document_id}"
            )

            evidence_items = extract_evidence_from_pdf(
                file_path=file_path,
                document_id=document_id
            )

            print(
                f"   Candidate evidence trovate: "
                f"{len(evidence_items)}"
            )

            inserted, skipped = save_evidence(
                evidence_items
            )

            print(
                f"   [OK] Evidence inserite: "
                f"{inserted}"
            )

            print(
                f"   [INFO] Evidence già esistenti: "
                f"{skipped}"
            )

        except Exception as exc:

            print(
                f"   [ERRORE] {file_path}: {exc}"
            )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    process_documents()
