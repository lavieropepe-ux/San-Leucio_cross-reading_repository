import hashlib
import json
import os
import re
from typing import Optional

from openai import OpenAI
from supabase import create_client, Client


# ============================================================
# CONFIGURAZIONE
# ============================================================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv(
    "SUPABASE_SERVICE_ROLE_KEY"
)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

OPENAI_MODEL = os.getenv(
    "OPENAI_MODEL",
    "gpt-5.6-luna"
)


if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise ValueError(
        "SUPABASE_URL / "
        "SUPABASE_SERVICE_ROLE_KEY mancanti."
    )

if not OPENAI_API_KEY:
    raise ValueError(
        "OPENAI_API_KEY mancante."
    )


supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY
)

openai_client = OpenAI(
    api_key=OPENAI_API_KEY
)


# ============================================================
# TABELLE
# ============================================================

DOCUMENTS_TABLE = "documents"
EVIDENCE_TABLE = "evidence"

COMPONENT_PROPOSALS_TABLE = (
    "component_proposals"
)

COMPONENT_PROPOSAL_EVIDENCE_TABLE = (
    "component_proposal_evidence"
)

PHASE_PROPOSALS_TABLE = (
    "phase_proposals"
)

PHASE_PROPOSAL_EVIDENCE_TABLE = (
    "phase_proposal_evidence"
)


# ============================================================
# CONFIGURAZIONE PIPELINE
# ============================================================
#
# Questo script realizza ESCLUSIVAMENTE:
#
# DOCUMENTS + EVIDENCE
#          ↓
#     CROSS-READING AI
#          ↓
# COMPONENT_PROPOSALS
# PHASE_PROPOSALS
#
# Non crea:
# - components
# - phases
#
# Non valida niente.
#
# Tutte le proposte entrano con:
#
# review_status = to_review
#
# ============================================================


# Evitiamo prompt giganteschi.
# Se le evidence sono numerose vengono analizzate a gruppi
# e successivamente consolidate.

MAX_CHARS_PER_BATCH = 70000


# ============================================================
# LETTURA DOCUMENTS
# ============================================================

def get_documents() -> dict:
    """
    Restituisce un dizionario:

    document_id -> metadati della fonte
    """

    response = (
        supabase
        .table(DOCUMENTS_TABLE)
        .select(
            "id,"
            "title,"
            "author,"
            "source_date,"
            "source_type,"
            "source_status,"
            "historical_period,"
            "file_path"
        )
        .execute()
    )

    documents = {}

    for row in response.data or []:
        documents[row["id"]] = row

    return documents


# ============================================================
# LETTURA EVIDENCE
# ============================================================

def get_all_evidence() -> list[dict]:
    """
    Recupera tutte le evidence non esplicitamente rejected.

    Le evidence possono essere ancora to_review:
    servono come materiale documentario per formulare
    proposte che saranno successivamente controllate
    dal ricercatore.
    """

    all_rows = []

    page_size = 1000
    start = 0

    while True:

        end = start + page_size - 1

        response = (
            supabase
            .table(EVIDENCE_TABLE)
            .select(
                "id,"
                "document_id,"
                "page_reference,"
                "source_excerpt,"
                "objective_information,"
                "element,"
                "temporal_reference,"
                "start_year,"
                "end_year,"
                "temporal_precision,"
                "transformation_type,"
                "spatial_information,"
                "spatial_relation,"
                "location_description,"
                "review_status"
            )
            .neq(
                "review_status",
                "rejected"
            )
            .range(
                start,
                end
            )
            .execute()
        )

        rows = response.data or []

        all_rows.extend(rows)

        if len(rows) < page_size:
            break

        start += page_size

    return all_rows


# ============================================================
# PREPARAZIONE CORPUS PER IA
# ============================================================

def build_ai_evidence(
    evidence_rows: list[dict],
    documents: dict
) -> list[dict]:

    prepared = []

    for evidence in evidence_rows:

        document = documents.get(
            evidence.get("document_id"),
            {}
        )

        prepared.append(
            {
                "evidence_id":
                    evidence["id"],

                "document_id":
                    evidence.get(
                        "document_id"
                    ),

                "document_title":
                    document.get("title"),

                "document_author":
                    document.get("author"),

                "document_date":
                    document.get(
                        "source_date"
                    ),

                "document_type":
                    document.get(
                        "source_type"
                    ),

                "historical_period":
                    document.get(
                        "historical_period"
                    ),

                "page":
                    evidence.get(
                        "page_reference"
                    ),

                "excerpt":
                    evidence.get(
                        "source_excerpt"
                    ),

                "objective_information":
                    evidence.get(
                        "objective_information"
                    ),

                "element":
                    evidence.get(
                        "element"
                    ),

                "temporal_reference":
                    evidence.get(
                        "temporal_reference"
                    ),

                "start_year":
                    evidence.get(
                        "start_year"
                    ),

                "end_year":
                    evidence.get(
                        "end_year"
                    ),

                "temporal_precision":
                    evidence.get(
                        "temporal_precision"
                    ),

                "transformation":
                    evidence.get(
                        "transformation_type"
                    ),

                "spatial_information":
                    evidence.get(
                        "spatial_information"
                    ),

                "spatial_relation":
                    evidence.get(
                        "spatial_relation"
                    ),

                "location_description":
                    evidence.get(
                        "location_description"
                    ),
            }
        )

    return prepared


# ============================================================
# CREAZIONE BATCH
# ============================================================

def split_into_batches(
    evidence_rows: list[dict]
) -> list[list[dict]]:

    batches = []

    current_batch = []
    current_chars = 0

    for evidence in evidence_rows:

        serialized = json.dumps(
            evidence,
            ensure_ascii=False
        )

        item_chars = len(serialized)

        if (
            current_batch
            and current_chars + item_chars
            > MAX_CHARS_PER_BATCH
        ):

            batches.append(
                current_batch
            )

            current_batch = []
            current_chars = 0

        current_batch.append(
            evidence
        )

        current_chars += item_chars

    if current_batch:
        batches.append(
            current_batch
        )

    return batches


# ============================================================
# PROMPT DI ANALISI
# ============================================================

ANALYSIS_PROMPT = """
Sei un assistente di ricerca che supporta
un ricercatore umano nell'analisi
storico-architettonica del Real Sito di San Leucio.

Ricevi EVIDENCE DOCUMENTARIE estratte da fonti.

Devi effettuare un cross-reading delle evidence
e formulare esclusivamente PROPOSTE.

Non devi stabilire verità definitive.

============================================================
OBIETTIVO 1 – COMPONENT PROPOSALS
============================================================

Individua possibili componenti del sistema
architettonico, produttivo, infrastrutturale
o territoriale.

Un componente può essere, ad esempio:

- complesso;
- edificio;
- corpo di fabbrica;
- spazio;
- ambiente;
- infrastruttura;
- elemento produttivo;
- elemento architettonico significativo.

ATTENZIONE:

un termine presente nella fonte
NON deve diventare automaticamente un componente.

Ad esempio:

- una generica "volta"
- una generica "muratura"
- un verbo
- un processo

non devono necessariamente diventare componenti autonomi.

Devi usare il contesto delle evidence.

Denominazioni differenti possono riferirsi
alla stessa entità.

Puoi proporre una loro unificazione
SOLTANTO quando le evidence lo rendono plausibile.

Non dare mai per certa l'equivalenza.

============================================================
OBIETTIVO 2 – PHASE PROPOSALS
============================================================

Individua possibili fasi storico-trasformative.

ATTENZIONE:

UN ANNO NON È AUTOMATICAMENTE UNA FASE.

Una fase deve derivare da un insieme coerente
di evidence che suggerisce:

- una configurazione;
- una trasformazione;
- una costruzione;
- un ampliamento;
- una demolizione;
- un cambiamento funzionale;
- una riorganizzazione del sistema;
- un intervallo storico significativo.

Se non esistono elementi sufficienti
per proporre una fase,
non proporla.

============================================================
CROSS-READING
============================================================

Quando possibile confronta evidence provenienti
da documenti differenti.

Considera:

- concordanze;
- differenze;
- riferimenti cronologici;
- trasformazioni;
- denominazioni;
- relazioni spaziali;
- provenienza documentaria.

La presenza di più fonti può rafforzare
una proposta, ma non rende automaticamente
vera l'interpretazione.

============================================================
REGOLE
============================================================

1. Usa esclusivamente le evidence fornite.

2. Non utilizzare conoscenze esterne.

3. Non inventare date.

4. Non inventare edifici.

5. Non inventare relazioni.

6. Non inventare evidence_id.

7. Ogni proposta DEVE indicare gli evidence_id
   che la sostengono.

8. Se una proposta è debole,
   assegna confidence bassa.

9. Se le fonti sono contraddittorie,
   dichiaralo nella reason.

10. Confidence indica la solidità documentaria
    della PROPOSTA.

11. Confidence NON rappresenta
    una probabilità di verità storica.

12. Nessuna proposta è validated.

13. Il ricercatore umano deciderà
    successivamente se:
    - correggerla;
    - validarla;
    - respingerla.

============================================================
OUTPUT
============================================================

Restituisci ESCLUSIVAMENTE JSON valido.

Struttura obbligatoria:

{
  "components": [
    {
      "proposed_name": "...",
      "proposed_type": "...",
      "category": "...",
      "spatial_level": "...",
      "description": "...",
      "confidence": 0.0,
      "reason": "...",
      "evidence_ids": ["uuid", "uuid"]
    }
  ],

  "phases": [
    {
      "proposed_code": "...",
      "proposed_name": "...",
      "start_year": null,
      "end_year": null,
      "chronological_range": "...",
      "proposed_description": "...",
      "confidence": 0.0,
      "reason": "...",
      "evidence_ids": ["uuid", "uuid"]
    }
  ]
}

Non inserire testo prima o dopo il JSON.
"""


# ============================================================
# PULIZIA JSON
# ============================================================

def parse_json_response(
    raw_text: str
) -> dict:

    text = (
        raw_text
        or ""
    ).strip()

    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"\s*```$",
        "",
        text
    )

    text = text.strip()

    try:
        result = json.loads(text)

    except json.JSONDecodeError:

        start = text.find("{")
        end = text.rfind("}")

        if (
            start == -1
            or end == -1
            or end <= start
        ):
            raise ValueError(
                "La risposta AI non contiene "
                "un JSON valido."
            )

        result = json.loads(
            text[start:end + 1]
        )

    if not isinstance(result, dict):
        raise ValueError(
            "La risposta AI deve essere "
            "un oggetto JSON."
        )

    if not isinstance(
        result.get("components"),
        list
    ):
        result["components"] = []

    if not isinstance(
        result.get("phases"),
        list
    ):
        result["phases"] = []

    return result


# ============================================================
# CHIAMATA OPENAI
# ============================================================

def analyze_batch(
    evidence_batch: list[dict],
    batch_number: int,
    total_batches: int
) -> dict:

    evidence_json = json.dumps(
        evidence_batch,
        ensure_ascii=False,
        indent=2
    )

    user_prompt = (
        f"BATCH {batch_number}/{total_batches}\n\n"
        "Analizza le seguenti evidence:\n\n"
        + evidence_json
    )

    response = (
        openai_client.responses.create(
            model=OPENAI_MODEL,

            instructions=ANALYSIS_PROMPT,

            input=user_prompt
        )
    )

    return parse_json_response(
        response.output_text
    )


# ============================================================
# CONSOLIDAMENTO MULTI-BATCH
# ============================================================

CONSOLIDATION_PROMPT = """
Ricevi una serie di PROPOSTE PRELIMINARI
generate da più batch dello stesso corpus documentario.

Devi consolidarle.

Il risultato rimane una PROPOSTA AI,
non conoscenza validata.

COMPONENTI:

- unisci duplicati evidenti;
- conserva tutte le evidence_id pertinenti;
- non fondere entità differenti senza supporto;
- non trasformare termini generici in componenti
  se il corpus non lo sostiene.

FASI:

- non trasformare ogni anno in una fase;
- unisci candidati cronologicamente e
  documentalmente coerenti;
- mantieni separate configurazioni differenti;
- non inventare date mancanti.

Non utilizzare informazioni esterne.

Ogni evidence_id restituito deve provenire
dalle proposte ricevute.

Restituisci esclusivamente:

{
  "components": [...],
  "phases": [...]
}

con gli stessi campi delle proposte originali.
"""


def consolidate_results(
    preliminary_results: list[dict]
) -> dict:

    if len(preliminary_results) == 1:
        return preliminary_results[0]

    compact = {
        "batch_results":
            preliminary_results
    }

    response = (
        openai_client.responses.create(
            model=OPENAI_MODEL,

            instructions=CONSOLIDATION_PROMPT,

            input=json.dumps(
                compact,
                ensure_ascii=False
            )
        )
    )

    return parse_json_response(
        response.output_text
    )


# ============================================================
# UTILITÀ
# ============================================================

def sanitize_evidence_ids(
    values,
    valid_ids: set[str]
) -> list[str]:

    if not isinstance(values, list):
        return []

    result = []

    for value in values:

        if (
            isinstance(value, str)
            and value in valid_ids
        ):
            result.append(value)

    return sorted(set(result))


def safe_confidence(
    value
) -> Optional[float]:

    try:
        number = float(value)

    except (
        TypeError,
        ValueError
    ):
        return None

    return round(
        max(
            0.0,
            min(
                number,
                1.0
            )
        ),
        3
    )


def safe_year(
    value
) -> Optional[int]:

    if value in (
        None,
        "",
        "null"
    ):
        return None

    try:
        return int(value)

    except (
        TypeError,
        ValueError
    ):
        return None


def normalize_for_key(
    value
) -> str:

    if value is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value).strip().lower()
    )


# ============================================================
# SOURCE KEY
# ============================================================

def component_source_key(
    proposal: dict,
    evidence_ids: list[str]
) -> str:
    """
    Genera una chiave stabile per una proposta di componente.

    La chiave NON dipende dal proposed_name,
    perché il nome può cambiare tra due esecuzioni AI.

    Dipende invece da:
    - evidence documentarie che sostengono la proposta;
    - tipo di componente;
    - categoria;
    - livello spaziale.

    In questo modo:
    "Gran Filanda"
    "Filanda Grande"
    "Real Filanda"

    possono continuare a riferirsi alla stessa proposta
    se il supporto documentario e la classificazione
    rimangono gli stessi.
    """

    normalized_evidence_ids = "|".join(
        sorted(set(evidence_ids))
    )

    raw = "|".join(
        [
            "component",

            normalize_for_key(
                proposal.get(
                    "proposed_type"
                )
            ),

            normalize_for_key(
                proposal.get(
                    "category"
                )
            ),

            normalize_for_key(
                proposal.get(
                    "spatial_level"
                )
            ),

            normalized_evidence_ids,
        ]
    )

    digest = hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:24]

    return f"CMP_{digest}"
    return f"CMP_{digest}"


def phase_source_key(
    proposal: dict,
    evidence_ids: list[str]
) -> str:
    """
    Genera una chiave stabile per una proposta di fase.

    La chiave NON dipende dal proposed_name.

    La stessa fase potrebbe infatti essere denominata
    diversamente dall'AI in esecuzioni successive.

    La chiave dipende da:
    - evidence documentarie;
    - start_year;
    - end_year.

    Il nome resta quindi modificabile senza
    modificare l'identità tecnica della proposta.
    """

    normalized_evidence_ids = "|".join(
        sorted(set(evidence_ids))
    )

    raw = "|".join(
        [
            "phase",

            normalize_for_key(
                proposal.get(
                    "start_year"
                )
            ),

            normalize_for_key(
                proposal.get(
                    "end_year"
                )
            ),

            normalized_evidence_ids,
        ]
    )

    digest = hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:24]

    return f"PHA_{digest}"

# ============================================================
# RICERCA PROPOSTA ESISTENTE
# ============================================================

def find_component_proposal(
    source_key: str
):

    response = (
        supabase
        .table(
            COMPONENT_PROPOSALS_TABLE
        )
        .select(
            "id,review_status"
        )
        .eq(
            "source_key",
            source_key
        )
        .limit(1)
        .execute()
    )

    if response.data:
        return response.data[0]

    return None


def find_phase_proposal(
    source_key: str
):

    response = (
        supabase
        .table(
            PHASE_PROPOSALS_TABLE
        )
        .select(
            "id,review_status"
        )
        .eq(
            "source_key",
            source_key
        )
        .limit(1)
        .execute()
    )

    if response.data:
        return response.data[0]

    return None


# ============================================================
# RELAZIONI COMPONENT PROPOSAL ↔ EVIDENCE
# ============================================================

def component_link_exists(
    proposal_id: str,
    evidence_id: str
) -> bool:

    response = (
        supabase
        .table(
            COMPONENT_PROPOSAL_EVIDENCE_TABLE
        )
        .select(
            "component_proposal_id"
        )
        .eq(
            "component_proposal_id",
            proposal_id
        )
        .eq(
            "evidence_id",
            evidence_id
        )
        .limit(1)
        .execute()
    )

    return bool(response.data)


def link_component_evidence(
    proposal_id: str,
    evidence_ids: list[str]
):

    for evidence_id in evidence_ids:

        if component_link_exists(
            proposal_id,
            evidence_id
        ):
            continue

        (
            supabase
            .table(
                COMPONENT_PROPOSAL_EVIDENCE_TABLE
            )
            .insert(
                {
                    "component_proposal_id":
                        proposal_id,

                    "evidence_id":
                        evidence_id,

                    "relation_type":
                        "supports"
                }
            )
            .execute()
        )


# ============================================================
# RELAZIONI PHASE PROPOSAL ↔ EVIDENCE
# ============================================================

def phase_link_exists(
    proposal_id: str,
    evidence_id: str
) -> bool:

    response = (
        supabase
        .table(
            PHASE_PROPOSAL_EVIDENCE_TABLE
        )
        .select(
            "phase_proposal_id"
        )
        .eq(
            "phase_proposal_id",
            proposal_id
        )
        .eq(
            "evidence_id",
            evidence_id
        )
        .limit(1)
        .execute()
    )

    return bool(response.data)


def link_phase_evidence(
    proposal_id: str,
    evidence_ids: list[str]
):

    for evidence_id in evidence_ids:

        if phase_link_exists(
            proposal_id,
            evidence_id
        ):
            continue

        (
            supabase
            .table(
                PHASE_PROPOSAL_EVIDENCE_TABLE
            )
            .insert(
                {
                    "phase_proposal_id":
                        proposal_id,

                    "evidence_id":
                        evidence_id,

                    "relation_type":
                        "supports"
                }
            )
            .execute()
        )


# ============================================================
# SALVATAGGIO COMPONENT PROPOSAL
# ============================================================

def save_component_proposal(
    proposal: dict,
    valid_ids: set[str]
):

    evidence_ids = (
        sanitize_evidence_ids(
            proposal.get(
                "evidence_ids"
            ),
            valid_ids
        )
    )

    # Una proposta senza evidence
    # non viene accettata dal sistema.
    if not evidence_ids:
        return None, "invalid"

    proposed_name = (
        str(
            proposal.get(
                "proposed_name"
            )
            or ""
        )
        .strip()
    )

    if not proposed_name:
        return None, "invalid"

    source_key = (
        component_source_key(
            proposal,
            evidence_ids
        )
    )

    existing = (
        find_component_proposal(
            source_key
        )
    )

    explanation = (
        proposal.get("reason")
        or
        "Proposta generata mediante "
        "cross-reading AI delle evidence."
    )

    payload = {
        "source_key":
            source_key,

        "proposed_name":
            proposed_name,

        "proposed_type":
            proposal.get(
                "proposed_type"
            ),

        "category":
            proposal.get(
                "category"
            ),

        "spatial_level":
            proposal.get(
                "spatial_level"
            ),

        "description":
            proposal.get(
                "description"
            ),

        "proposal_origin":
            "ai",

        "ai_model":
            OPENAI_MODEL,

        "ai_explanation":
            explanation,

        "confidence":
            safe_confidence(
                proposal.get(
                    "confidence"
                )
            )
    }

    if existing:

        proposal_id = existing["id"]

        # Una proposta già presa in carico
        # dal ricercatore NON viene sovrascritta.
        if (
            existing.get(
                "review_status"
            )
            != "to_review"
        ):

            link_component_evidence(
                proposal_id,
                evidence_ids
            )

            return (
                proposal_id,
                "protected"
            )

        (
            supabase
            .table(
                COMPONENT_PROPOSALS_TABLE
            )
            .update(payload)
            .eq(
                "id",
                proposal_id
            )
            .execute()
        )

        link_component_evidence(
            proposal_id,
            evidence_ids
        )

        return (
            proposal_id,
            "updated"
        )

    payload.update(
        {
            "parent_proposal_id":
                None,

            "review_status":
                "to_review",

            "reviewed_by":
                None,

            "reviewed_at":
                None,

            "review_notes":
                None
        }
    )

    response = (
        supabase
        .table(
            COMPONENT_PROPOSALS_TABLE
        )
        .insert(payload)
        .execute()
    )

    proposal_id = (
        response.data[0]["id"]
    )

    link_component_evidence(
        proposal_id,
        evidence_ids
    )

    return (
        proposal_id,
        "created"
    )


# ============================================================
# SALVATAGGIO PHASE PROPOSAL
# ============================================================

def save_phase_proposal(
    proposal: dict,
    valid_ids: set[str]
):

    evidence_ids = (
        sanitize_evidence_ids(
            proposal.get(
                "evidence_ids"
            ),
            valid_ids
        )
    )

    if not evidence_ids:
        return None, "invalid"

    proposed_name = (
        str(
            proposal.get(
                "proposed_name"
            )
            or ""
        )
        .strip()
    )

    if not proposed_name:
        return None, "invalid"

    start_year = safe_year(
        proposal.get(
            "start_year"
        )
    )

    end_year = safe_year(
        proposal.get(
            "end_year"
        )
    )

    if (
        start_year is not None
        and end_year is not None
        and start_year > end_year
    ):
        (
            start_year,
            end_year
        ) = (
            end_year,
            start_year
        )

    proposal_for_key = dict(
        proposal
    )

    proposal_for_key[
        "start_year"
    ] = start_year

    proposal_for_key[
        "end_year"
    ] = end_year

    source_key = (
        phase_source_key(
            proposal_for_key,
            evidence_ids
        )
    )

    existing = (
        find_phase_proposal(
            source_key
        )
    )

    explanation = (
        proposal.get("reason")
        or
        "Proposta di fase generata "
        "mediante cross-reading AI."
    )

    payload = {
        "source_key":
            source_key,

        "proposed_code":
            proposal.get(
                "proposed_code"
            ),

        "proposed_name":
            proposed_name,

        "start_year":
            start_year,

        "end_year":
            end_year,

        "chronological_range":
            proposal.get(
                "chronological_range"
            ),

        "proposed_description":
            proposal.get(
                "proposed_description"
            ),

        "proposal_origin":
            "ai",

        "ai_model":
            OPENAI_MODEL,

        "ai_explanation":
            explanation,

        "confidence":
            safe_confidence(
                proposal.get(
                    "confidence"
                )
            )
    }

    if existing:

        proposal_id = (
            existing["id"]
        )

        if (
            existing.get(
                "review_status"
            )
            != "to_review"
        ):

            link_phase_evidence(
                proposal_id,
                evidence_ids
            )

            return (
                proposal_id,
                "protected"
            )

        (
            supabase
            .table(
                PHASE_PROPOSALS_TABLE
            )
            .update(payload)
            .eq(
                "id",
                proposal_id
            )
            .execute()
        )

        link_phase_evidence(
            proposal_id,
            evidence_ids
        )

        return (
            proposal_id,
            "updated"
        )

    payload.update(
        {
            "review_status":
                "to_review",

            "reviewed_by":
                None,

            "reviewed_at":
                None,

            "review_notes":
                None
        }
    )

    response = (
        supabase
        .table(
            PHASE_PROPOSALS_TABLE
        )
        .insert(payload)
        .execute()
    )

    proposal_id = (
        response.data[0]["id"]
    )

    link_phase_evidence(
        proposal_id,
        evidence_ids
    )

    return (
        proposal_id,
        "created"
    )


# ============================================================
# SALVATAGGIO COMPLESSIVO
# ============================================================

def save_ai_result(
    result: dict,
    evidence_rows: list[dict]
):

    valid_ids = {
        row["id"]
        for row in evidence_rows
    }

    stats = {
        "component_created": 0,
        "component_updated": 0,
        "component_protected": 0,
        "component_invalid": 0,

        "phase_created": 0,
        "phase_updated": 0,
        "phase_protected": 0,
        "phase_invalid": 0
    }

    for proposal in result.get(
        "components",
        []
    ):

        _, status = (
            save_component_proposal(
                proposal,
                valid_ids
            )
        )

        key = (
            "component_"
            + status
        )

        if key in stats:
            stats[key] += 1

    for proposal in result.get(
        "phases",
        []
    ):

        _, status = (
            save_phase_proposal(
                proposal,
                valid_ids
            )
        )

        key = (
            "phase_"
            + status
        )

        if key in stats:
            stats[key] += 1

    return stats


# ============================================================
# MAIN
# ============================================================

def process_proposals():

    print("=" * 80)
    print(
        "SAN LEUCIO – AI CROSS-READING"
    )
    print("=" * 80)

    print(
        f"Modello AI: "
        f"{OPENAI_MODEL}"
    )

    documents = get_documents()

    evidence_rows = (
        get_all_evidence()
    )

    print(
        f"Evidence disponibili: "
        f"{len(evidence_rows)}"
    )

    if not evidence_rows:

        print(
            "Nessuna evidence disponibile."
        )

        print(
            "Eseguire prima il workflow "
            "di estrazione delle evidence."
        )

        return

    source_ids = {
        row.get("document_id")
        for row in evidence_rows
        if row.get("document_id")
    }

    print(
        f"Fonti coinvolte: "
        f"{len(source_ids)}"
    )

    prepared = build_ai_evidence(
        evidence_rows,
        documents
    )

    batches = split_into_batches(
        prepared
    )

    print(
        f"Batch AI: "
        f"{len(batches)}"
    )

    preliminary_results = []

    for index, batch in enumerate(
        batches,
        start=1
    ):

        print(
            f"\nAnalisi batch "
            f"{index}/{len(batches)} "
            f"({len(batch)} evidence)..."
        )

        result = analyze_batch(
            evidence_batch=batch,
            batch_number=index,
            total_batches=len(batches)
        )

        preliminary_results.append(
            result
        )

        print(
            f"   Componenti candidati: "
            f"{len(result.get('components', []))}"
        )

        print(
            f"   Fasi candidate: "
            f"{len(result.get('phases', []))}"
        )

    print(
        "\nConsolidamento "
        "delle proposte..."
    )

    final_result = (
        consolidate_results(
            preliminary_results
        )
    )

    print(
        f"Component proposals finali: "
        f"{len(final_result.get('components', []))}"
    )

    print(
        f"Phase proposals finali: "
        f"{len(final_result.get('phases', []))}"
    )

    stats = save_ai_result(
        final_result,
        evidence_rows
    )

    print("\n" + "=" * 80)
    print("SALVATAGGIO COMPLETATO")
    print("=" * 80)

    print(
        "Component proposals create: "
        f"{stats['component_created']}"
    )

    print(
        "Component proposals aggiornate: "
        f"{stats['component_updated']}"
    )

    print(
        "Component proposals protette "
        "(già in revisione/validate/rejected): "
        f"{stats['component_protected']}"
    )

    print(
        "Component proposals scartate "
        "per dati insufficienti: "
        f"{stats['component_invalid']}"
    )

    print(
        "Phase proposals create: "
        f"{stats['phase_created']}"
    )

    print(
        "Phase proposals aggiornate: "
        f"{stats['phase_updated']}"
    )

    print(
        "Phase proposals protette "
        "(già in revisione/validate/rejected): "
        f"{stats['phase_protected']}"
    )

    print(
        "Phase proposals scartate "
        "per dati insufficienti: "
        f"{stats['phase_invalid']}"
    )

    print("\nATTENZIONE:")

    print(
        "Questi risultati sono soltanto "
        "PROPOSTE AI."
    )

    print(
        "Nessun componente e nessuna fase "
        "sono stati inseriti nelle tabelle finali."
    )

    print(
        "Il ricercatore deve ora "
        "revisionare le proposte in Supabase."
    )


if __name__ == "__main__":
    process_proposals()
