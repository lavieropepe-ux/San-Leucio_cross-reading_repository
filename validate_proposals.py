import os
from datetime import datetime, timezone

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

EVIDENCE_TABLE = "evidence"


COMPONENT_PROPOSALS_TABLE = (
    "component_proposals"
)

COMPONENT_PROPOSAL_EVIDENCE_TABLE = (
    "component_proposal_evidence"
)

COMPONENTS_TABLE = "components"

COMPONENT_EVIDENCE_TABLE = (
    "component_evidence"
)


PHASE_PROPOSALS_TABLE = (
    "phase_proposals"
)

PHASE_PROPOSAL_EVIDENCE_TABLE = (
    "phase_proposal_evidence"
)

PHASES_TABLE = "phases"

PHASE_EVIDENCE_TABLE = (
    "phase_evidence"
)


# ============================================================
# PRINCIPIO METODOLOGICO
# ============================================================
#
# Questo script NON decide cosa sia vero.
#
# Il ricercatore ha già operato in Supabase:
#
# to_review
#      ↓
# in_review
#      ↓
# validated / rejected
#
# Questo script promuove esclusivamente
# le proposte human-validated.
#
# ============================================================


def now_iso():
    return datetime.now(
        timezone.utc
    ).isoformat()


# ============================================================
# CONTROLLO VALIDAZIONE RICERCATORE
# ============================================================

def researcher_validation_complete(
    proposal: dict
) -> bool:

    if (
        proposal.get(
            "review_status"
        )
        != "validated"
    ):
        return False

    if not proposal.get(
        "reviewed_by"
    ):
        return False

    if not proposal.get(
        "reviewed_at"
    ):
        return False

    return True


# ============================================================
# RECUPERO EVIDENCE COLLEGATE
# ============================================================

def get_linked_evidence_ids(
    table_name: str,
    proposal_column: str,
    proposal_id: str
) -> list[str]:

    response = (
        supabase
        .table(table_name)
        .select("evidence_id")
        .eq(
            proposal_column,
            proposal_id
        )
        .execute()
    )

    return [
        row["evidence_id"]
        for row in response.data or []
    ]


# ============================================================
# CONTROLLO EVIDENCE
# ============================================================

def evidence_are_admissible(
    evidence_ids: list[str]
) -> tuple[bool, str]:

    if not evidence_ids:
        return (
            False,
            "nessuna evidence collegata"
        )

    response = (
        supabase
        .table(EVIDENCE_TABLE)
        .select(
            "id,"
            "review_status"
        )
        .in_(
            "id",
            evidence_ids
        )
        .execute()
    )

    rows = response.data or []

    if len(rows) != len(
        set(evidence_ids)
    ):

        return (
            False,
            "alcune evidence non esistono"
        )

    rejected = [
        row["id"]
        for row in rows
        if row.get(
            "review_status"
        ) == "rejected"
    ]

    if rejected:

        return (
            False,
            f"{len(rejected)} evidence "
            "sono state rifiutate"
        )

    return (
        True,
        "ok"
    )


# ============================================================
# COMPONENT PROPOSALS VALIDATE
# ============================================================

def get_validated_component_proposals():

    response = (
        supabase
        .table(
            COMPONENT_PROPOSALS_TABLE
        )
        .select("*")
        .eq(
            "review_status",
            "validated"
        )
        .execute()
    )

    return response.data or []


def find_component_by_proposal(
    proposal_id: str
):

    response = (
        supabase
        .table(
            COMPONENTS_TABLE
        )
        .select("id")
        .eq(
            "proposal_id",
            proposal_id
        )
        .limit(1)
        .execute()
    )

    if response.data:
        return response.data[0]["id"]

    return None


# ============================================================
# RISOLUZIONE COMPONENTE PADRE
# ============================================================

def find_parent_component_id(
    parent_proposal_id
):

    if not parent_proposal_id:
        return None

    response = (
        supabase
        .table(
            COMPONENTS_TABLE
        )
        .select("id")
        .eq(
            "proposal_id",
            parent_proposal_id
        )
        .limit(1)
        .execute()
    )

    if response.data:
        return response.data[0]["id"]

    return None


# ============================================================
# COMPONENT ↔ EVIDENCE
# ============================================================

def component_evidence_exists(
    component_id: str,
    evidence_id: str
) -> bool:

    response = (
        supabase
        .table(
            COMPONENT_EVIDENCE_TABLE
        )
        .select(
            "component_id"
        )
        .eq(
            "component_id",
            component_id
        )
        .eq(
            "evidence_id",
            evidence_id
        )
        .limit(1)
        .execute()
    )

    return bool(response.data)


def copy_component_evidence(
    component_id: str,
    evidence_ids: list[str]
):

    inserted = 0

    for evidence_id in evidence_ids:

        if component_evidence_exists(
            component_id,
            evidence_id
        ):
            continue

        (
            supabase
            .table(
                COMPONENT_EVIDENCE_TABLE
            )
            .insert(
                {
                    "component_id":
                        component_id,

                    "evidence_id":
                        evidence_id,

                    "relation_type":
                        "supported_by"
                }
            )
            .execute()
        )

        inserted += 1

    return inserted


# ============================================================
# PROMOZIONE COMPONENTE
# ============================================================

def promote_component(
    proposal: dict
):

    name = (
        proposal.get(
            "proposed_name"
        )
        or ""
    ).strip()

    if not name:

        print(
            "[SKIP COMPONENT] "
            "Nome mancante."
        )

        return False

    if not researcher_validation_complete(
        proposal
    ):

        print(
            f"[SKIP COMPONENT] "
            f"{name}: "
            "validazione umana incompleta."
        )

        return False

    evidence_ids = (
        get_linked_evidence_ids(
            COMPONENT_PROPOSAL_EVIDENCE_TABLE,
            "component_proposal_id",
            proposal["id"]
        )
    )

    admissible, reason = (
        evidence_are_admissible(
            evidence_ids
        )
    )

    if not admissible:

        print(
            f"[SKIP COMPONENT] "
            f"{name}: {reason}."
        )

        return False

    parent_component_id = (
        find_parent_component_id(
            proposal.get(
                "parent_proposal_id"
            )
        )
    )

    payload = {
        "proposal_id":
            proposal["id"],

        "parent_component_id":
            parent_component_id,

        "name":
            name,

        "component_type":
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

        "knowledge_status":
            "researcher_validated",

        "review_status":
            "validated",

        "validated_by":
            proposal.get(
                "reviewed_by"
            ),

        "validated_at":
            proposal.get(
                "reviewed_at"
            )
            or now_iso(),

        "validation_notes":
            proposal.get(
                "review_notes"
            )
    }

    component_id = (
        find_component_by_proposal(
            proposal["id"]
        )
    )

    if component_id:

        (
            supabase
            .table(
                COMPONENTS_TABLE
            )
            .update(payload)
            .eq(
                "id",
                component_id
            )
            .execute()
        )

        action = "UPDATED"

    else:

        response = (
            supabase
            .table(
                COMPONENTS_TABLE
            )
            .insert(payload)
            .execute()
        )

        component_id = (
            response.data[0]["id"]
        )

        action = "CREATED"

    links = (
        copy_component_evidence(
            component_id,
            evidence_ids
        )
    )

    print(
        f"[{action} COMPONENT] "
        f"{name} | "
        f"evidence={len(evidence_ids)} | "
        f"nuovi link={links}"
    )

    return True


# ============================================================
# PHASE PROPOSALS VALIDATE
# ============================================================

def get_validated_phase_proposals():

    response = (
        supabase
        .table(
            PHASE_PROPOSALS_TABLE
        )
        .select("*")
        .eq(
            "review_status",
            "validated"
        )
        .execute()
    )

    return response.data or []


def find_phase_by_proposal(
    proposal_id: str
):

    response = (
        supabase
        .table(
            PHASES_TABLE
        )
        .select("id")
        .eq(
            "proposal_id",
            proposal_id
        )
        .limit(1)
        .execute()
    )

    if response.data:
        return response.data[0]["id"]

    return None


# ============================================================
# CODICE FASE
# ============================================================

def safe_phase_code(
    proposal: dict
) -> str:

    proposed_code = (
        proposal.get(
            "proposed_code"
        )
        or ""
    ).strip()

    if proposed_code:
        return proposed_code

    # codice stabile derivato dalla UUID
    return (
        "PH_"
        + proposal["id"][:8].upper()
    )


# ============================================================
# PHASE ↔ EVIDENCE
# ============================================================

def phase_evidence_exists(
    phase_id: str,
    evidence_id: str
) -> bool:

    response = (
        supabase
        .table(
            PHASE_EVIDENCE_TABLE
        )
        .select(
            "phase_id"
        )
        .eq(
            "phase_id",
            phase_id
        )
        .eq(
            "evidence_id",
            evidence_id
        )
        .limit(1)
        .execute()
    )

    return bool(response.data)


def copy_phase_evidence(
    phase_id: str,
    evidence_ids: list[str]
):

    inserted = 0

    for evidence_id in evidence_ids:

        if phase_evidence_exists(
            phase_id,
            evidence_id
        ):
            continue

        (
            supabase
            .table(
                PHASE_EVIDENCE_TABLE
            )
            .insert(
                {
                    "phase_id":
                        phase_id,

                    "evidence_id":
                        evidence_id,

                    "relation_type":
                        "supported_by"
                }
            )
            .execute()
        )

        inserted += 1

    return inserted


# ============================================================
# PROMOZIONE FASE
# ============================================================

def promote_phase(
    proposal: dict
):

    name = (
        proposal.get(
            "proposed_name"
        )
        or ""
    ).strip()

    if not name:

        print(
            "[SKIP PHASE] "
            "Nome mancante."
        )

        return False

    if not researcher_validation_complete(
        proposal
    ):

        print(
            f"[SKIP PHASE] "
            f"{name}: "
            "validazione umana incompleta."
        )

        return False

    evidence_ids = (
        get_linked_evidence_ids(
            PHASE_PROPOSAL_EVIDENCE_TABLE,
            "phase_proposal_id",
            proposal["id"]
        )
    )

    admissible, reason = (
        evidence_are_admissible(
            evidence_ids
        )
    )

    if not admissible:

        print(
            f"[SKIP PHASE] "
            f"{name}: {reason}."
        )

        return False

    start_year = proposal.get(
        "start_year"
    )

    end_year = proposal.get(
        "end_year"
    )

    if (
        start_year is not None
        and end_year is not None
        and start_year > end_year
    ):

        print(
            f"[SKIP PHASE] "
            f"{name}: intervallo "
            "cronologico non valido."
        )

        return False

    payload = {
        "proposal_id":
            proposal["id"],

        "code":
            safe_phase_code(
                proposal
            ),

        "name":
            name,

        "start_year":
            start_year,

        "end_year":
            end_year,

        "chronological_range":
            proposal.get(
                "chronological_range"
            ),

        "description":
            proposal.get(
                "proposed_description"
            ),

        "knowledge_status":
            "researcher_validated",

        "review_status":
            "validated",

        "validated_by":
            proposal.get(
                "reviewed_by"
            ),

        "validated_at":
            proposal.get(
                "reviewed_at"
            )
            or now_iso(),

        "validation_notes":
            proposal.get(
                "review_notes"
            )
    }

    phase_id = (
        find_phase_by_proposal(
            proposal["id"]
        )
    )

    if phase_id:

        (
            supabase
            .table(
                PHASES_TABLE
            )
            .update(payload)
            .eq(
                "id",
                phase_id
            )
            .execute()
        )

        action = "UPDATED"

    else:

        response = (
            supabase
            .table(
                PHASES_TABLE
            )
            .insert(payload)
            .execute()
        )

        phase_id = (
            response.data[0]["id"]
        )

        action = "CREATED"

    links = (
        copy_phase_evidence(
            phase_id,
            evidence_ids
        )
    )

    print(
        f"[{action} PHASE] "
        f"{name} | "
        f"evidence={len(evidence_ids)} | "
        f"nuovi link={links}"
    )

    return True


# ============================================================
# MAIN
# ============================================================

def validate_proposals():

    print("=" * 80)

    print(
        "SAN LEUCIO – "
        "HUMAN-VALIDATED KNOWLEDGE"
    )

    print("=" * 80)

    component_proposals = (
        get_validated_component_proposals()
    )

    phase_proposals = (
        get_validated_phase_proposals()
    )

    print(
        f"Component proposals "
        f"marcate validated: "
        f"{len(component_proposals)}"
    )

    print(
        f"Phase proposals "
        f"marcate validated: "
        f"{len(phase_proposals)}"
    )

    component_promoted = 0
    component_skipped = 0

    phase_promoted = 0
    phase_skipped = 0

    print("\n" + "-" * 80)
    print("COMPONENTS")
    print("-" * 80)

    for proposal in component_proposals:

        if promote_component(
            proposal
        ):
            component_promoted += 1

        else:
            component_skipped += 1

    print("\n" + "-" * 80)
    print("PHASES")
    print("-" * 80)

    for proposal in phase_proposals:

        if promote_phase(
            proposal
        ):
            phase_promoted += 1

        else:
            phase_skipped += 1

    print("\n" + "=" * 80)
    print("RISULTATO")
    print("=" * 80)

    print(
        f"Components promossi/aggiornati: "
        f"{component_promoted}"
    )

    print(
        f"Components non promossi: "
        f"{component_skipped}"
    )

    print(
        f"Phases promosse/aggiornate: "
        f"{phase_promoted}"
    )

    print(
        f"Phases non promosse: "
        f"{phase_skipped}"
    )

    print(
        "\nLe tabelle components e phases "
        "contengono esclusivamente entità "
        "che hanno superato la validazione "
        "del ricercatore."
    )


if __name__ == "__main__":
    validate_proposals()
