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

COMPONENT_PROPOSALS_TABLE = "component_proposals"
COMPONENT_PROPOSAL_EVIDENCE_TABLE = (
    "component_proposal_evidence"
)

COMPONENTS_TABLE = "components"
COMPONENT_EVIDENCE_TABLE = (
    "component_evidence"
)

PHASE_PROPOSALS_TABLE = "phase_proposals"
PHASE_PROPOSAL_EVIDENCE_TABLE = (
    "phase_proposal_evidence"
)

PHASES_TABLE = "phases"
PHASE_EVIDENCE_TABLE = (
    "phase_evidence"
)

EVIDENCE_TABLE = "evidence"


def now_iso():
    return datetime.now(
        timezone.utc
    ).isoformat()


# ============================================================
# VALIDAZIONE UMANA
# ============================================================

def researcher_validation_complete(
    proposal: dict
) -> bool:
    """
    Per entrare nelle tabelle finali:

    1. review_status deve essere validated;
    2. reviewed_by deve essere compilato;
    3. reviewed_at deve esistere.
    """

    return (
        proposal.get("review_status")
        == "validated"

        and bool(
            proposal.get("reviewed_by")
        )

        and bool(
            proposal.get("reviewed_at")
        )
    )


# ============================================================
# CONTROLLO EVIDENCE
# ============================================================

def get_linked_evidence(
    junction_table: str,
    proposal_column: str,
    proposal_id: str
):

    response = (
        supabase
        .table(junction_table)
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


def evidence_are_admissible(
    evidence_ids: list[str]
) -> bool:
    """
    Una proposta senza evidence non può
    entrare nella conoscenza finale.

    Se una evidence collegata è stata
    esplicitamente rejected,
    la proposta viene bloccata.
    """

    if not evidence_ids:
        return False

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

    if not rows:
        return False

    for row in rows:

        if row.get(
            "review_status"
        ) == "rejected":

            return False

    return True


# ============================================================
# COMPONENTS
# ============================================================

def get_component_proposals():

    response = (
        supabase
        .table(COMPONENT_PROPOSALS_TABLE)
        .select("*")
        .eq(
            "review_status",
            "validated"
        )
        .execute()
    )

    return response.data or []


def find_component(
    proposal_id: str
):

    response = (
        supabase
        .table(COMPONENTS_TABLE)
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


def promote_component(
    proposal: dict
):

    if not researcher_validation_complete(
        proposal
    ):
        print(
            f"[SKIP] {proposal.get('proposed_name')}: "
            "validazione del ricercatore incompleta."
        )
        return

    evidence_ids = get_linked_evidence(
        COMPONENT_PROPOSAL_EVIDENCE_TABLE,
        "component_proposal_id",
        proposal["id"]
    )

    if not evidence_are_admissible(
        evidence_ids
    ):
        print(
            f"[SKIP] {proposal.get('proposed_name')}: "
            "evidence mancanti o rifiutate."
        )
        return

    payload = {
        "proposal_id":
            proposal["id"],

        "name":
            proposal.get(
                "proposed_name"
            ),

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

    existing_id = find_component(
        proposal["id"]
    )

    if existing_id:

        (
            supabase
            .table(COMPONENTS_TABLE)
            .update(payload)
            .eq(
                "id",
                existing_id
            )
            .execute()
        )

        component_id = existing_id

    else:

        response = (
            supabase
            .table(COMPONENTS_TABLE)
            .insert(payload)
            .execute()
        )

        component_id = (
            response.data[0]["id"]
        )

    for evidence_id in evidence_ids:

        existing = (
            supabase
            .table(
                COMPONENT_EVIDENCE_TABLE
            )
            .select("component_id")
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

        if existing.data:
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

    print(
        f"[VALIDATED COMPONENT] "
        f"{proposal.get('proposed_name')}"
    )


# ============================================================
# PHASES
# ============================================================

def get_phase_proposals():

    response = (
        supabase
        .table(PHASE_PROPOSALS_TABLE)
        .select("*")
        .eq(
            "review_status",
            "validated"
        )
        .execute()
    )

    return response.data or []


def find_phase(
    proposal_id: str
):

    response = (
        supabase
        .table(PHASES_TABLE)
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


def safe_phase_code(
    proposal: dict
):

    if proposal.get(
        "proposed_code"
    ):
        return proposal[
            "proposed_code"
        ]

    return (
        "PH_"
        + proposal["id"][:8]
    )


def promote_phase(
    proposal: dict
):

    if not researcher_validation_complete(
        proposal
    ):

        print(
            f"[SKIP] {proposal.get('proposed_name')}: "
            "validazione del ricercatore incompleta."
        )

        return

    evidence_ids = get_linked_evidence(
        PHASE_PROPOSAL_EVIDENCE_TABLE,
        "phase_proposal_id",
        proposal["id"]
    )

    if not evidence_are_admissible(
        evidence_ids
    ):

        print(
            f"[SKIP] {proposal.get('proposed_name')}: "
            "evidence mancanti o rifiutate."
        )

        return

    payload = {
        "proposal_id":
            proposal["id"],

        "code":
            safe_phase_code(
                proposal
            ),

        "name":
            proposal.get(
                "proposed_name"
            ),

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

        "description":
            proposal.get(
                "proposed_description"
            ),

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

    existing_id = find_phase(
        proposal["id"]
    )

    if existing_id:

        (
            supabase
            .table(PHASES_TABLE)
            .update(payload)
            .eq(
                "id",
                existing_id
            )
            .execute()
        )

        phase_id = existing_id

    else:

        response = (
            supabase
            .table(PHASES_TABLE)
            .insert(payload)
            .execute()
        )

        phase_id = (
            response.data[0]["id"]
        )

    for evidence_id in evidence_ids:

        existing = (
            supabase
            .table(
                PHASE_EVIDENCE_TABLE
            )
            .select("phase_id")
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

        if existing.data:
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

    print(
        f"[VALIDATED PHASE] "
        f"{proposal.get('proposed_name')}"
    )


# ============================================================
# MAIN
# ============================================================

def validate_proposals():

    print("=" * 80)
    print("SAN LEUCIO – HUMAN VALIDATION")
    print("=" * 80)

    components = (
        get_component_proposals()
    )

    phases = (
        get_phase_proposals()
    )

    print(
        f"Component proposals "
        f"marcate validated: "
        f"{len(components)}"
    )

    print(
        f"Phase proposals "
        f"marcate validated: "
        f"{len(phases)}"
    )

    for proposal in components:
        promote_component(
            proposal
        )

    for proposal in phases:
        promote_phase(
            proposal
        )

    print("\n" + "=" * 80)

    print(
        "Sono entrate nelle tabelle finali "
        "solo proposte verificate "
        "dal ricercatore."
    )

    print("=" * 80)


if __name__ == "__main__":
    validate_proposals()
