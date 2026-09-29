import hashlib
import os
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from supabase import Client, create_client


# ============================================================
# CONFIGURATION
# ============================================================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL:
    raise ValueError("SUPABASE_URL mancante.")

if not SUPABASE_SERVICE_ROLE_KEY:
    raise ValueError("SUPABASE_SERVICE_ROLE_KEY mancante.")

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY,
)

GENERATOR_NAME = "rule_based_v1"

DEFAULT_REVIEW_STATUS = "to_review"

VALID_REVIEW_STATUSES = {
    "to_review",
    "in_review",
    "validated",
    "rejected",
}


# ============================================================
# CONTROLLED NORMALIZATION FOR COMPONENT CANDIDATES
# ============================================================
#
# Queste equivalenze NON rappresentano una verità storica.
# Servono soltanto a normalizzare alcuni termini documentari
# affinché evidence riferite allo stesso elemento possano essere
# raggruppate automaticamente.
# ============================================================

COMPONENT_NORMALIZATION = {
    "belvedere": "Belvedere",
    "filanda": "Filanda",
    "filanda reale": "Filanda Reale",
    "gran filanda": "Gran Filanda",
    "setificio": "Setificio",
    "setificio di san leucio": "Setificio di San Leucio",
    "opificio": "Opificio",
    "opificio borbonico": "Opificio borbonico",
    "fabbrica della seta": "Fabbrica della seta",

    "salone": "Salone",
    "salone delle feste": "Salone delle Feste",
    "salone da ballo": "Salone da Ballo",
    "sala del trono": "Sala del Trono",

    "residenza reale": "Residenza reale",
    "appartamento del re": "Appartamento del Re",
    "stanze reali": "Stanze reali",
    "alloggi operai": "Alloggi operai",

    "quartiere san ferdinando": "Quartiere San Ferdinando",

    "acquedotto": "Acquedotto",
    "acquedotto carolino": "Acquedotto Carolino",

    "bagno grande": "Bagno Grande",

    "fontana": "Fontana",
    "vasca": "Vasca",
    "canale": "Canale",
    "condotto": "Condotto",
    "cavedio": "Cavedio",

    "cortile": "Cortile",
    "giardino": "Giardino",
    "strada": "Strada",
    "piazza": "Piazza",

    "trattaglio": "Trattaglio",
    "telaio": "Telaio",
}


# Termini che rimangono evidence documentarie,
# ma non diventano automaticamente componenti autonomi.

GENERIC_ELEMENTS = {
    "volta",
    "muratura",
    "muro",
    "parete",
    "pilastro",
    "colonna",
    "scala",
    "portico",
    "terrazza",
    "facciata",
    "prospetto",
    "copertura",
    "tetto",
    "bagno",
    "trattura",
    "tessitura",
    "filatura",
    "produzione",
}


# ============================================================
# COMPONENT CLASSIFICATION
# ============================================================

BUILDING_COMPONENTS = {
    "Belvedere",
    "Filanda",
    "Filanda Reale",
    "Gran Filanda",
    "Setificio",
    "Setificio di San Leucio",
    "Opificio",
    "Opificio borbonico",
    "Fabbrica della seta",
    "Residenza reale",
}

SPACE_COMPONENTS = {
    "Salone",
    "Salone delle Feste",
    "Salone da Ballo",
    "Sala del Trono",
    "Appartamento del Re",
    "Stanze reali",
    "Alloggi operai",
    "Bagno Grande",
    "Cavedio",
    "Cortile",
}

INFRASTRUCTURE_COMPONENTS = {
    "Acquedotto",
    "Acquedotto Carolino",
    "Fontana",
    "Vasca",
    "Canale",
    "Condotto",
}

PRODUCTIVE_COMPONENTS = {
    "Trattaglio",
    "Telaio",
}

TERRITORIAL_COMPONENTS = {
    "Quartiere San Ferdinando",
    "Giardino",
    "Strada",
    "Piazza",
}


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def normalize_text(value: Optional[str]) -> str:
    """
    Normalizza spazi e maiuscole/minuscole
    per confronti deterministici.
    """

    if value is None:
        return ""

    value = str(value).replace("\u00a0", " ")
    value = re.sub(r"\s+", " ", value).strip()

    return value.casefold()


def split_elements(value: Optional[str]) -> List[str]:
    """
    Divide il campo evidence.element quando contiene
    più elementi separati da virgole o punto e virgola.
    """

    if not value:
        return []

    parts = re.split(r"[,;]", str(value))

    result = []

    for part in parts:
        cleaned = re.sub(r"\s+", " ", part).strip()

        if cleaned:
            result.append(cleaned)

    return result


def to_int(value: Any) -> Optional[int]:

    if value is None or value == "":
        return None

    try:
        return int(value)

    except (TypeError, ValueError):
        return None


def fetch_all(
    table_name: str,
    page_size: int = 1000,
) -> List[Dict[str, Any]]:
    """
    Legge tutte le righe di una tabella Supabase
    usando la paginazione.
    """

    rows = []

    start = 0

    while True:

        end = start + page_size - 1

        response = (
            supabase
            .table(table_name)
            .select("*")
            .range(start, end)
            .execute()
        )

        batch = response.data or []

        rows.extend(batch)

        if len(batch) < page_size:
            break

        start += page_size

    return rows


def distinct_source_count(
    evidence_rows: List[Dict[str, Any]],
) -> int:
    """
    Conta quante fonti/documenti differenti
    sostengono la proposta.
    """

    document_ids = {
        str(row.get("document_id"))
        for row in evidence_rows
        if row.get("document_id")
    }

    return len(document_ids)


def deterministic_confidence(
    evidence_count: int,
    source_count: int,
) -> float:
    """
    Punteggio deterministico di supporto documentario.

    NON rappresenta la probabilità che la proposta
    sia storicamente vera.
    """

    score = (
        0.40
        + min(evidence_count, 5) * 0.08
        + min(source_count, 3) * 0.10
    )

    return round(
        min(score, 1.0),
        2,
    )


# ============================================================
# SOURCE KEYS
# ============================================================

def component_source_key(
    canonical_name: str,
    proposed_type: str,
    category: str,
    spatial_level: str,
    evidence_ids: List[str],
) -> str:

    raw = "|".join(
        [
            normalize_text(canonical_name),
            proposed_type,
            category,
            spatial_level,
            *sorted(evidence_ids),
        ]
    )

    digest = hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:24]

    return f"CMP_{digest}"


def phase_source_key(
    start_year: Optional[int],
    end_year: Optional[int],
    evidence_ids: List[str],
) -> str:

    raw = "|".join(
        [
            str(start_year or ""),
            str(end_year or ""),
            *sorted(evidence_ids),
        ]
    )

    digest = hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:24]

    return f"PHS_{digest}"


# ============================================================
# COMPONENT CLASSIFICATION
# ============================================================

def classify_component(
    canonical_name: str,
) -> Tuple[str, str, str]:

    if canonical_name in BUILDING_COMPONENTS:

        return (
            "building",
            "architectural",
            "building",
        )

    if canonical_name in SPACE_COMPONENTS:

        return (
            "space",
            "architectural",
            "space",
        )

    if canonical_name in INFRASTRUCTURE_COMPONENTS:

        return (
            "infrastructure",
            "technical_infrastructure",
            "site",
        )

    if canonical_name in PRODUCTIVE_COMPONENTS:

        return (
            "productive_element",
            "productive",
            "object",
        )

    if canonical_name in TERRITORIAL_COMPONENTS:

        return (
            "territorial_element",
            "urban_territorial",
            "site",
        )

    return (
        "component",
        "architectural",
        "building",
    )


# ============================================================
# COMPONENT CANDIDATE GENERATION
# ============================================================

def build_component_candidates(
    evidence_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:

    grouped = defaultdict(dict)

    for evidence in evidence_rows:

        # Evidence respinte dal ricercatore
        # non vengono utilizzate.
        if evidence.get("review_status") == "rejected":
            continue

        evidence_id = evidence.get("id")

        if not evidence_id:
            continue

        elements = split_elements(
            evidence.get("element")
        )

        for raw_element in elements:

            normalized = normalize_text(
                raw_element
            )

            if not normalized:
                continue

            # Termini generici restano evidence,
            # ma non diventano component proposals.
            if normalized in GENERIC_ELEMENTS:
                continue

            canonical_name = (
                COMPONENT_NORMALIZATION.get(
                    normalized
                )
            )

            # Solo termini del vocabolario controllato
            # possono generare automaticamente una proposta.
            if not canonical_name:
                continue

            grouped[
                canonical_name
            ][str(evidence_id)] = evidence


    candidates = []

    for canonical_name, evidence_map in grouped.items():

        supporting_evidence = list(
            evidence_map.values()
        )

        evidence_ids = sorted(
            evidence_map.keys()
        )

        evidence_count = len(
            supporting_evidence
        )

        source_count = distinct_source_count(
            supporting_evidence
        )

        (
            proposed_type,
            category,
            spatial_level,
        ) = classify_component(
            canonical_name
        )

        confidence = (
            deterministic_confidence(
                evidence_count,
                source_count,
            )
        )

        reason = (
            f"Proposta rule-based ottenuta "
            f"raggruppando {evidence_count} "
            f"evidence documentarie "
            f"riconducibili al termine controllato "
            f"'{canonical_name}', provenienti da "
            f"{source_count} fonte/i. "
            f"La proposta richiede verifica, "
            f"eventuale correzione e validazione "
            f"da parte del ricercatore."
        )

        description = (
            f"Componente candidato emerso dal "
            f"raggruppamento automatico delle "
            f"evidence associate a "
            f"'{canonical_name}'."
        )

        candidates.append(
            {

                "source_key":
                    component_source_key(
                        canonical_name,
                        proposed_type,
                        category,
                        spatial_level,
                        evidence_ids,
                    ),

                "proposed_name":
                    canonical_name,

                "proposed_type":
                    proposed_type,

                "category":
                    category,

                "spatial_level":
                    spatial_level,

                "description":
                    description,

                "proposal_origin":
                    "rule_based",

                # Campi mantenuti solo per
                # compatibilità con lo schema esistente.
                "ai_model":
                    GENERATOR_NAME,

                "ai_explanation":
                    reason,

                "confidence":
                    confidence,

                # Ogni nuova proposta nasce sempre
                # da revisionare.
                "review_status":
                    DEFAULT_REVIEW_STATUS,

                "evidence_ids":
                    evidence_ids,
            }
        )

    candidates.sort(
        key=lambda row:
        row["proposed_name"].casefold()
    )

    return candidates


# ============================================================
# PHASE CANDIDATE GENERATION
# ============================================================

def has_explicit_transformation(
    evidence: Dict[str, Any],
) -> bool:

    value = evidence.get(
        "transformation_type"
    )

    return bool(
        value
        and str(value).strip()
    )


def build_phase_candidates(
    evidence_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:

    grouped = defaultdict(dict)

    for evidence in evidence_rows:

        if evidence.get(
            "review_status"
        ) == "rejected":
            continue

        # Per generare una phase proposal
        # non basta trovare una data.
        if not has_explicit_transformation(
            evidence
        ):
            continue

        start_year = to_int(
            evidence.get("start_year")
        )

        end_year = to_int(
            evidence.get("end_year")
        )

        if (
            start_year is None
            and end_year is None
        ):
            continue

        evidence_id = evidence.get("id")

        if not evidence_id:
            continue

        key = (
            start_year,
            end_year,
        )

        grouped[
            key
        ][str(evidence_id)] = evidence


    candidates = []

    for (
        start_year,
        end_year,
    ), evidence_map in grouped.items():

        supporting_evidence = list(
            evidence_map.values()
        )

        evidence_ids = sorted(
            evidence_map.keys()
        )

        evidence_count = len(
            supporting_evidence
        )

        source_count = distinct_source_count(
            supporting_evidence
        )

        # Una singola evidence datata
        # non diventa automaticamente una fase.
        if (
            evidence_count < 2
            and source_count < 2
        ):
            continue


        if (
            start_year is not None
            and end_year is not None
            and end_year != start_year
        ):

            proposed_name = (
                f"Candidate transformation phase "
                f"{start_year}-{end_year}"
            )

            proposed_code = (
                f"PH_{start_year}_{end_year}"
            )

            chronological_range = (
                f"{start_year}-{end_year}"
            )

        else:

            year = (
                start_year
                if start_year is not None
                else end_year
            )

            proposed_name = (
                f"Candidate transformation phase "
                f"{year}"
            )

            proposed_code = (
                f"PH_{year}"
            )

            chronological_range = str(
                year
            )


        confidence = (
            deterministic_confidence(
                evidence_count,
                source_count,
            )
        )

        reason = (
            f"Proposta rule-based costruita "
            f"raggruppando {evidence_count} evidence "
            f"con riferimento cronologico compatibile "
            f"e indicazione esplicita di trasformazione, "
            f"provenienti da {source_count} fonte/i. "
            f"La presenza di una data non viene "
            f"considerata, da sola, sufficiente "
            f"a definire una fase storica. "
            f"La proposta deve essere verificata "
            f"e validata dal ricercatore."
        )

        description = (
            "Fase storico-trasformativa candidata "
            "generata automaticamente da evidence "
            "cronologiche associate a trasformazioni "
            "esplicite."
        )

        candidates.append(
            {

                "source_key":
                    phase_source_key(
                        start_year,
                        end_year,
                        evidence_ids,
                    ),

                "proposed_code":
                    proposed_code,

                "proposed_name":
                    proposed_name,

                "start_year":
                    start_year,

                "end_year":
                    end_year,

                "chronological_range":
                    chronological_range,

                "proposed_description":
                    description,

                "proposal_origin":
                    "rule_based",

                # Campi legacy mantenuti
                # per compatibilità.
                "ai_model":
                    GENERATOR_NAME,

                "ai_explanation":
                    reason,

                "confidence":
                    confidence,

                "review_status":
                    DEFAULT_REVIEW_STATUS,

                "evidence_ids":
                    evidence_ids,
            }
        )


    candidates.sort(
        key=lambda row: (
            row.get("start_year")
            or row.get("end_year")
            or 999999,

            row["proposed_name"],
        )
    )

    return candidates


# ============================================================
# REVIEW STATUS VALIDATION
# ============================================================

def validate_existing_review_status(
    status: Optional[str],
) -> str:

    status = (
        status
        or DEFAULT_REVIEW_STATUS
    )

    if status not in VALID_REVIEW_STATUSES:

        raise ValueError(
            "review_status non valido "
            f"trovato nel database: {status!r}. "
            "Valori ammessi: "
            f"{sorted(VALID_REVIEW_STATUSES)}"
        )

    return status


# ============================================================
# COMPONENT PROPOSAL PERSISTENCE
# ============================================================

def save_component_proposal(
    candidate: Dict[str, Any],
) -> Tuple[str, str]:

    evidence_ids = candidate[
        "evidence_ids"
    ]

    payload = {
        key: value
        for key, value
        in candidate.items()
        if key != "evidence_ids"
    }

    existing_response = (
        supabase
        .table("component_proposals")
        .select(
            "id, review_status"
        )
        .eq(
            "source_key",
            candidate["source_key"],
        )
        .limit(1)
        .execute()
    )

    existing = (
        existing_response.data
        or []
    )


    # --------------------------------------------------------
    # PROPOSTA GIÀ ESISTENTE
    # --------------------------------------------------------

    if existing:

        proposal_id = str(
            existing[0]["id"]
        )

        current_status = (
            validate_existing_review_status(
                existing[0].get(
                    "review_status"
                )
            )
        )


        # ====================================================
        # PROTEZIONE DELLA REVISIONE UMANA
        # ====================================================
        #
        # Se il ricercatore ha già iniziato la revisione,
        # il generatore automatico NON modifica più
        # la proposta.
        #
        # ====================================================

        if current_status in {
            "in_review",
            "validated",
            "rejected",
        }:

            link_component_evidence(
                proposal_id,
                evidence_ids,
            )

            return (
                "protected",
                proposal_id,
            )


        # ====================================================
        # SOLO to_review PUÒ ESSERE AGGIORNATO
        # ====================================================

        update_payload = (
            payload.copy()
        )

        update_payload[
            "review_status"
        ] = "to_review"

        (
            supabase
            .table("component_proposals")
            .update(update_payload)
            .eq(
                "id",
                proposal_id,
            )
            .execute()
        )

        link_component_evidence(
            proposal_id,
            evidence_ids,
        )

        return (
            "updated",
            proposal_id,
        )


    # --------------------------------------------------------
    # NUOVA PROPOSTA
    # --------------------------------------------------------

    insert_response = (
        supabase
        .table("component_proposals")
        .insert(payload)
        .execute()
    )

    inserted = (
        insert_response.data
        or []
    )

    if not inserted:

        raise RuntimeError(
            "Inserimento component proposal "
            "fallito: "
            f"{candidate['source_key']}"
        )

    proposal_id = str(
        inserted[0]["id"]
    )

    link_component_evidence(
        proposal_id,
        evidence_ids,
    )

    return (
        "inserted",
        proposal_id,
    )


# ============================================================
# PHASE PROPOSAL PERSISTENCE
# ============================================================

def save_phase_proposal(
    candidate: Dict[str, Any],
) -> Tuple[str, str]:

    evidence_ids = candidate[
        "evidence_ids"
    ]

    payload = {
        key: value
        for key, value
        in candidate.items()
        if key != "evidence_ids"
    }

    existing_response = (
        supabase
        .table("phase_proposals")
        .select(
            "id, review_status"
        )
        .eq(
            "source_key",
            candidate["source_key"],
        )
        .limit(1)
        .execute()
    )

    existing = (
        existing_response.data
        or []
    )


    if existing:

        proposal_id = str(
            existing[0]["id"]
        )

        current_status = (
            validate_existing_review_status(
                existing[0].get(
                    "review_status"
                )
            )
        )


        # Non sovrascrivere mai una proposta
        # già presa in carico dal ricercatore.

        if current_status in {
            "in_review",
            "validated",
            "rejected",
        }:

            link_phase_evidence(
                proposal_id,
                evidence_ids,
            )

            return (
                "protected",
                proposal_id,
            )


        # Solo to_review può essere
        # aggiornato automaticamente.

        update_payload = (
            payload.copy()
        )

        update_payload[
            "review_status"
        ] = "to_review"

        (
            supabase
            .table("phase_proposals")
            .update(
                update_payload
            )
            .eq(
                "id",
                proposal_id,
            )
            .execute()
        )

        link_phase_evidence(
            proposal_id,
            evidence_ids,
        )

        return (
            "updated",
            proposal_id,
        )


    # Nuova proposta

    insert_response = (
        supabase
        .table("phase_proposals")
        .insert(payload)
        .execute()
    )

    inserted = (
        insert_response.data
        or []
    )

    if not inserted:

        raise RuntimeError(
            "Inserimento phase proposal "
            "fallito: "
            f"{candidate['source_key']}"
        )

    proposal_id = str(
        inserted[0]["id"]
    )

    link_phase_evidence(
        proposal_id,
        evidence_ids,
    )

    return (
        "inserted",
        proposal_id,
    )


# ============================================================
# COMPONENT PROPOSAL ↔️ EVIDENCE
# ============================================================

def link_component_evidence(
    proposal_id: str,
    evidence_ids: List[str],
) -> None:

    if not evidence_ids:
        return

    rows = [
        {
            "component_proposal_id":
                proposal_id,

            "evidence_id":
                evidence_id,

            "relation_type":
                "supports",
        }

        for evidence_id
        in evidence_ids
    ]

    (
        supabase
        .table(
            "component_proposal_evidence"
        )
        .upsert(
            rows,
            on_conflict=(
                "component_proposal_id,"
                "evidence_id"
            ),
        )
        .execute()
    )


# ============================================================
# PHASE PROPOSAL ↔️ EVIDENCE
# ============================================================

def link_phase_evidence(
    proposal_id: str,
    evidence_ids: List[str],
) -> None:

    if not evidence_ids:
        return

    rows = [
        {
            "phase_proposal_id":
                proposal_id,

            "evidence_id":
                evidence_id,

            "relation_type":
                "supports",
        }

        for evidence_id
        in evidence_ids
    ]

    (
        supabase
        .table(
            "phase_proposal_evidence"
        )
        .upsert(
            rows,
            on_conflict=(
                "phase_proposal_id,"
                "evidence_id"
            ),
        )
        .execute()
    )


# ============================================================
# MAIN PROCESS
# ============================================================

def process_proposals():

    documents = fetch_all(
        "documents"
    )

    all_evidence = fetch_all(
        "evidence"
    )


    # Evidence esplicitamente respinte
    # dal ricercatore non partecipano
    # più alla generazione.

    usable_evidence = [
        row

        for row
        in all_evidence

        if row.get(
            "review_status"
        ) != "rejected"
    ]


    component_candidates = (
        build_component_candidates(
            usable_evidence
        )
    )

    phase_candidates = (
        build_phase_candidates(
            usable_evidence
        )
    )


    print("=" * 72)

    print(
        "SAN LEUCIO - "
        "RULE-BASED CROSS-READING"
    )

    print("=" * 72)

    print(
        f"Documenti disponibili: "
        f"{len(documents)}"
    )

    print(
        f"Evidence disponibili: "
        f"{len(usable_evidence)}"
    )

    print(
        "Component proposals candidate: "
        f"{len(component_candidates)}"
    )

    print(
        "Phase proposals candidate: "
        f"{len(phase_candidates)}"
    )

    print()


    component_stats = defaultdict(
        int
    )

    phase_stats = defaultdict(
        int
    )


    # ========================================================
    # SAVE COMPONENT PROPOSALS
    # ========================================================

    for candidate in component_candidates:

        status, proposal_id = (
            save_component_proposal(
                candidate
            )
        )

        component_stats[
            status
        ] += 1

        print(
            f"[COMPONENT] "
            f"{status:9s} | "
            f"{candidate['proposed_name']} | "
            f"{proposal_id}"
        )


    # ========================================================
    # SAVE PHASE PROPOSALS
    # ========================================================

    for candidate in phase_candidates:

        status, proposal_id = (
            save_phase_proposal(
                candidate
            )
        )

        phase_stats[
            status
        ] += 1

        print(
            f"[PHASE]     "
            f"{status:9s} | "
            f"{candidate['proposed_name']} | "
            f"{proposal_id}"
        )


    # ========================================================
    # SUMMARY
    # ========================================================

    print()

    print("=" * 72)

    print("RIEPILOGO")

    print("=" * 72)


    print(
        "Component proposals -> "
        f"inserted: "
        f"{component_stats['inserted']}, "
        f"updated: "
        f"{component_stats['updated']}, "
        f"protected: "
        f"{component_stats['protected']}"
    )


    print(
        "Phase proposals     -> "
        f"inserted: "
        f"{phase_stats['inserted']}, "
        f"updated: "
        f"{phase_stats['updated']}, "
        f"protected: "
        f"{phase_stats['protected']}"
    )


    print()

    print(
        "REVIEW WORKFLOW:"
    )

    print(
        "to_review "
        "-> in_review "
        "-> validated"
    )

    print(
        "                     "
        "-> rejected"
    )

    print()

    print(
        "Gli stati in_review, "
        "validated e rejected sono "
        "controllati dal ricercatore "
        "e non vengono sovrascritti "
        "dai rerun automatici."
    )


# ============================================================
# START
# ============================================================

if _name_ == "_main_":

    process_proposals()
