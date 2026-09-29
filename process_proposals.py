import hashlib
import os
import re
from collections import defaultdict
from typing import Optional

from supabase import create_client, Client


# ============================================================
# CONFIGURAZIONE
# ============================================================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv(
    "SUPABASE_SERVICE_ROLE_KEY"
)

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise ValueError(
        "SUPABASE_URL / "
        "SUPABASE_SERVICE_ROLE_KEY mancanti."
    )


supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY
)


# ============================================================
# TABELLE
# ============================================================

DOCUMENTS_TABLE = "documents"
EVIDENCE_TABLE = "evidence"

COMPONENT_PROPOSALS_TABLE = "component_proposals"
COMPONENT_PROPOSAL_EVIDENCE_TABLE = (
    "component_proposal_evidence"
)

PHASE_PROPOSALS_TABLE = "phase_proposals"
PHASE_PROPOSAL_EVIDENCE_TABLE = (
    "phase_proposal_evidence"
)


# ============================================================
# PRINCIPIO METODOLOGICO
# ============================================================
#
# Questo script NON usa API AI / LLM.
#
# Produce PROPOSTE AUTOMATICHE RULE-BASED
# a partire esclusivamente dalle evidence presenti
# in Supabase.
#
# Non crea:
# - components
# - phases
#
# Non valida nulla.
#
# Tutte le proposte entrano come:
#
# review_status = to_review
#
# ============================================================


GENERATOR_NAME = "rule_based_v1"


# ============================================================
# VOCABOLARIO CONTROLLATO PER COMPONENTI
# ============================================================
#
# Serve esclusivamente per normalizzare alcune denominazioni
# documentarie.
#
# Non significa che l'equivalenza sia storicamente certa:
# il risultato resta una proposta da validare.
#
# ============================================================

COMPONENT_NORMALIZATION = {

    # Complessi / edifici / spazi
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
    "salone reale": "Salone Reale",
    "salone del belvedere": "Salone del Belvedere",
    "gran salone": "Gran Salone",
    "sala del trono": "Sala del Trono",

    "residenza reale": "Residenza reale",
    "appartamento del re": "Appartamento del Re",
    "stanze reali": "Stanze reali",
    "alloggi degli operai": "Alloggi degli operai",

    "quartiere san ferdinando":
        "Quartiere San Ferdinando",

    # Infrastrutture / acqua
    "acquedotto": "Acquedotto",
    "acquedotto carolino": "Acquedotto Carolino",
    "bagno grande": "Bagno Grande",
    "fontana": "Fontana",
    "vasca": "Vasca",
    "canale": "Canale",
    "condotto": "Condotto",
    "cavedio": "Cavedio",

    # Spazi aperti
    "cortile": "Cortile",
    "giardino": "Giardino",
    "strada": "Strada",
    "piazza": "Piazza",

    # Elementi produttivi
    "trattaglio": "Trattaglio",
    "telaio": "Telaio",
}


# ============================================================
# TERMINI TROPPO GENERICI
# ============================================================
#
# Possono essere conservati nelle evidence,
# ma non diventano automaticamente componenti.
#
# ============================================================

GENERIC_ELEMENTS = {
    "volta",
    "volta a botte",
    "volta a padiglione",
    "arco",
    "muratura",
    "muro",
    "pilastro",
    "colonna",
    "scalinata",
    "scalone",
    "scala",
    "portico",
    "terrazza",
    "facciata",
    "prospetto",
    "copertura",
    "bagno",
    "trattura",
    "tessitura",
}


# ============================================================
# CLASSIFICAZIONE RULE-BASED
# ============================================================

BUILDING_ELEMENTS = {
    "belvedere",
    "filanda",
    "filanda reale",
    "gran filanda",
    "setificio",
    "setificio di san leucio",
    "opificio",
    "opificio borbonico",
    "fabbrica della seta",
    "residenza reale",
}

SPACE_ELEMENTS = {
    "salone",
    "salone reale",
    "salone del belvedere",
    "gran salone",
    "sala del trono",
    "appartamento del re",
    "stanze reali",
    "alloggi degli operai",
    "cortile",
    "giardino",
    "piazza",
}

INFRASTRUCTURE_ELEMENTS = {
    "acquedotto",
    "acquedotto carolino",
    "fontana",
    "vasca",
    "canale",
    "condotto",
    "cavedio",
    "strada",
}

PRODUCTIVE_ELEMENTS = {
    "trattaglio",
    "telaio",
}

TERRITORIAL_ELEMENTS = {
    "quartiere san ferdinando",
}


# ============================================================
# UTILITÀ
# ============================================================

def normalize_text(value) -> str:

    if value is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value).strip().lower()
    )


def safe_year(value) -> Optional[int]:

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


def split_elements(element_value) -> list[str]:
    """
    main.py salva eventuali elementi multipli
    separati da virgole.
    """

    if not element_value:
        return []

    result = []

    for value in str(element_value).split(","):

        normalized = normalize_text(value)

        if normalized:
            result.append(normalized)

    return sorted(set(result))


def classify_component(
    canonical_element: str
) -> tuple[str, str, str]:

    if canonical_element in BUILDING_ELEMENTS:
        return (
            "building",
            "architectural",
            "building"
        )

    if canonical_element in SPACE_ELEMENTS:
        return (
            "space",
            "architectural",
            "space"
        )

    if canonical_element in INFRASTRUCTURE_ELEMENTS:
        return (
            "infrastructure",
            "infrastructural",
            "system"
        )

    if canonical_element in PRODUCTIVE_ELEMENTS:
        return (
            "productive_element",
            "productive",
            "element"
        )

    if canonical_element in TERRITORIAL_ELEMENTS:
        return (
            "urban_sector",
            "territorial",
            "district"
        )

    return (
        "documented_element",
        "undetermined",
        "element"
    )


# ============================================================
# LETTURA DOCUMENTS
# ============================================================

def get_documents() -> dict:

    response = (
        supabase
        .table(DOCUMENTS_TABLE)
        .select(
            "id,"
            "title,"
            "author,"
            "source_date,"
            "source_type,"
            "historical_period,"
            "file_path"
        )
        .execute()
    )

    return {
        row["id"]: row
        for row in response.data or []
    }


# ============================================================
# LETTURA EVIDENCE
# ============================================================

def get_all_evidence() -> list[dict]:

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
# COMPONENT PROPOSALS
# ============================================================

def generate_component_proposals(
    evidence_rows: list[dict]
) -> list[dict]:

    groups = defaultdict(list)

    for evidence in evidence_rows:

        for element in split_elements(
            evidence.get("element")
        ):

            if element in GENERIC_ELEMENTS:
                continue

            if element not in COMPONENT_NORMALIZATION:
                continue

            groups[element].append(
                evidence
            )

    proposals = []

    for canonical_element, rows in groups.items():

        evidence_ids = sorted({
            row["id"]
            for row in rows
        })

        document_ids = {
            row.get("document_id")
            for row in rows
            if row.get("document_id")
        }

        proposed_type, category, spatial_level = (
            classify_component(
                canonical_element
            )
        )

        proposed_name = (
            COMPONENT_NORMALIZATION[
                canonical_element
            ]
        )

        evidence_count = len(evidence_ids)
        source_count = len(document_ids)

        # Confidence = solidità del supporto documentario,
        # NON probabilità di verità storica.
        confidence = min(
            1.0,
            0.40
            + min(evidence_count, 5) * 0.08
            + min(source_count, 3) * 0.08
        )

        reason = (
            "Proposta rule-based ottenuta raggruppando "
            f"{evidence_count} evidence relative al termine "
            f"documentario '{canonical_element}', "
            f"provenienti da {source_count} fonte/i. "
            "La corrispondenza deve essere verificata "
            "dal ricercatore."
        )

        proposals.append(
            {
                # Chiave interna deterministica.
                # NON è proposed_name.
                "canonical_key":
                    canonical_element,

                "proposed_name":
                    proposed_name,

                "proposed_type":
                    proposed_type,

                "category":
                    category,

                "spatial_level":
                    spatial_level,

                "description":
                    (
                        "Componente candidato emerso "
                        "dal raggruppamento automatico "
                        "delle evidence documentarie."
                    ),

                "confidence":
                    round(confidence, 3),

                "reason":
                    reason,

                "evidence_ids":
                    evidence_ids,
            }
        )

    return proposals


# ============================================================
# PHASE PROPOSALS
# ============================================================
#
# Una data isolata NON diventa una fase.
#
# Una proposta viene prodotta solo quando esiste almeno
# un minimo di coerenza documentaria.
#
# ============================================================

def generate_phase_proposals(
    evidence_rows: list[dict]
) -> list[dict]:

    groups = defaultdict(list)

    for evidence in evidence_rows:

        start_year = safe_year(
            evidence.get("start_year")
        )

        end_year = safe_year(
            evidence.get("end_year")
        )

        transformation = (
            evidence.get(
                "transformation_type"
            )
        )

        if (
            start_year is None
            and end_year is None
        ):
            continue

        # Una data senza alcuna indicazione
        # trasformativa non basta da sola.
        if not transformation:
            continue

        groups[
            (
                start_year,
                end_year
            )
        ].append(
            evidence
        )

    proposals = []

    for (
        start_year,
        end_year
    ), rows in groups.items():

        evidence_ids = sorted({
            row["id"]
            for row in rows
        })

        document_ids = {
            row.get("document_id")
            for row in rows
            if row.get("document_id")
        }

        transformations = sorted({
            row.get(
                "transformation_type"
            )
            for row in rows
            if row.get(
                "transformation_type"
            )
        })

        evidence_count = len(evidence_ids)
        source_count = len(document_ids)

        # Evita anno = fase.
        #
        # Richiediamo almeno:
        # - 2 evidence
        # oppure
        # - 2 fonti differenti.
        if (
            evidence_count < 2
            and source_count < 2
        ):
            continue

        if (
            start_year is not None
            and end_year is not None
            and start_year == end_year
        ):
            chronological_range = str(
                start_year
            )

        elif (
            start_year is not None
            and end_year is not None
        ):
            chronological_range = (
                f"{start_year}–{end_year}"
            )

        elif start_year is not None:
            chronological_range = (
                f"da {start_year}"
            )

        elif end_year is not None:
            chronological_range = (
                f"fino a {end_year}"
            )

        else:
            chronological_range = None

        transformation_label = ", ".join(
            transformations
        )

        if chronological_range:
            proposed_name = (
                "Candidate transformation phase "
                f"{chronological_range}"
            )
        else:
            proposed_name = (
                "Candidate transformation phase"
            )

        proposed_code = (
            f"PH_{start_year or 'X'}_"
            f"{end_year or 'X'}"
        )

        confidence = min(
            1.0,
            0.35
            + min(evidence_count, 5) * 0.09
            + min(source_count, 3) * 0.10
        )

        reason = (
            "Proposta rule-based basata su "
            f"{evidence_count} evidence, "
            f"{source_count} fonte/i e sui seguenti "
            "indicatori espliciti di trasformazione: "
            f"{transformation_label}. "
            "La coincidenza cronologica non viene "
            "considerata automaticamente una fase: "
            "la proposta richiede validazione del ricercatore."
        )

        proposals.append(
            {
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
                    (
                        "Cluster cronologico-trasformativo "
                        "candidato ottenuto dal confronto "
                        "automatico delle evidence."
                    ),

                "confidence":
                    round(confidence, 3),

                "reason":
                    reason,

                "evidence_ids":
                    evidence_ids,
            }
        )

    return proposals


# ============================================================
# SOURCE KEYS
# ============================================================

def component_source_key(
    proposal: dict,
    evidence_ids: list[str]
) -> str:

    normalized_evidence_ids = "|".join(
        sorted(set(evidence_ids))
    )

    raw = "|".join(
        [
            "component",

            normalize_text(
                proposal.get(
                    "canonical_key"
                )
            ),

            normalize_text(
                proposal.get(
                    "proposed_type"
                )
            ),

            normalize_text(
                proposal.get(
                    "category"
                )
            ),

            normalize_text(
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


def phase_source_key(
    proposal: dict,
    evidence_ids: list[str]
) -> str:

    raw = "|".join(
        [
            "phase",

            normalize_text(
                proposal.get(
                    "start_year"
                )
            ),

            normalize_text(
                proposal.get(
                    "end_year"
                )
            ),

            "|".join(
                sorted(
                    set(evidence_ids)
                )
            ),
        ]
    )

    digest = hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:24]

    return f"PHA_{digest}"


# ============================================================
# EXISTING PROPOSALS
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
# LINKS
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
# SAVE COMPONENT
# ============================================================

def save_component_proposal(
    proposal: dict
):

    evidence_ids = sorted(
        set(
            proposal.get(
                "evidence_ids",
                []
            )
        )
    )

    if not evidence_ids:
        return "invalid"

    source_key = component_source_key(
        proposal,
        evidence_ids
    )

    existing = find_component_proposal(
        source_key
    )

    payload = {

        "source_key":
            source_key,

        "proposed_name":
            proposal["proposed_name"],

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
            "rule_based",

        "ai_model":
            GENERATOR_NAME,

        "ai_explanation":
            proposal.get(
                "reason"
            ),

        "confidence":
            proposal.get(
                "confidence"
            ),
    }

    if existing:

        proposal_id = existing["id"]

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

            return "protected"

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

        return "updated"

    payload.update(
        {
            "review_status":
                "to_review",

            "reviewed_by":
                None,

            "reviewed_at":
                None,

            "review_notes":
                None,

            "parent_proposal_id":
                None,
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

    proposal_id = response.data[0]["id"]

    link_component_evidence(
        proposal_id,
        evidence_ids
    )

    return "created"


# ============================================================
# SAVE PHASE
# ============================================================

def save_phase_proposal(
    proposal: dict
):

    evidence_ids = sorted(
        set(
            proposal.get(
                "evidence_ids",
                []
            )
        )
    )

    if not evidence_ids:
        return "invalid"

    source_key = phase_source_key(
        proposal,
        evidence_ids
    )

    existing = find_phase_proposal(
        source_key
    )

    payload = {

        "source_key":
            source_key,

        "proposed_code":
            proposal.get(
                "proposed_code"
            ),

        "proposed_name":
            proposal[
                "proposed_name"
            ],

        "start_year":
            proposal.get(
                "start_year"
            ),

        "end_year":
            proposal.get(
                "end_year"
            ),

        "chronological_range":
            proposal.get(
                "chronological_range"
            ),

        "proposed_description":
            proposal.get(
                "proposed_description"
            ),

        "proposal_origin":
            "rule_based",

        "ai_model":
            GENERATOR_NAME,

        "ai_explanation":
            proposal.get(
                "reason"
            ),

        "confidence":
            proposal.get(
                "confidence"
            ),
    }

    if existing:

        proposal_id = existing["id"]

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

            return "protected"

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

        return "updated"

    payload.update(
        {
            "review_status":
                "to_review",

            "reviewed_by":
                None,

            "reviewed_at":
                None,

            "review_notes":
                None,
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

    proposal_id = response.data[0]["id"]

    link_phase_evidence(
        proposal_id,
        evidence_ids
    )

    return "created"


# ============================================================
# MAIN
# ============================================================

def process_proposals():

    print("=" * 80)
    print(
        "SAN LEUCIO – "
        "RULE-BASED CROSS-READING"
    )
    print("=" * 80)

    documents = get_documents()

    evidence_rows = get_all_evidence()

    print(
        f"Documenti disponibili: "
        f"{len(documents)}"
    )

    print(
        f"Evidence disponibili: "
        f"{len(evidence_rows)}"
    )

    if not evidence_rows:

        print(
            "Nessuna evidence disponibile."
        )

        return

    component_proposals = (
        generate_component_proposals(
            evidence_rows
        )
    )

    phase_proposals = (
        generate_phase_proposals(
            evidence_rows
        )
    )

    print(
        f"Component proposals candidate: "
        f"{len(component_proposals)}"
    )

    print(
        f"Phase proposals candidate: "
        f"{len(phase_proposals)}"
    )

    stats = defaultdict(int)

    for proposal in component_proposals:

        status = save_component_proposal(
            proposal
        )

        stats[
            f"component_{status}"
        ] += 1

    for proposal in phase_proposals:

        status = save_phase_proposal(
            proposal
        )

        stats[
            f"phase_{status}"
        ] += 1

    print("\n" + "=" * 80)
    print("RISULTATO")
    print("=" * 80)

    print(
        "Component create: "
        f"{stats['component_created']}"
    )

    print(
        "Component aggiornate: "
        f"{stats['component_updated']}"
    )

    print(
        "Component protette: "
        f"{stats['component_protected']}"
    )

    print(
        "Phase create: "
        f"{stats['phase_created']}"
    )

    print(
        "Phase aggiornate: "
        f"{stats['phase_updated']}"
    )

    print(
        "Phase protette: "
        f"{stats['phase_protected']}"
    )

    print(
        "\nLe proposte sono state generate "
        "automaticamente mediante regole esplicite."
    )

    print(
        "Nessuna proposta è conoscenza validata."
    )

    print(
        "Il ricercatore deve revisionarle "
        "in Supabase."
    )


if __name__ == "__main__":
    process_proposals()
