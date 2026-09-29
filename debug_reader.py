import logging
import os
from io import BytesIO

from pypdf import PdfReader
from supabase import create_client, Client


logging.getLogger("pypdf").setLevel(logging.ERROR)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv(
    "SUPABASE_SERVICE_ROLE_KEY"
)

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise ValueError(
        "Variabili SUPABASE_URL e "
        "SUPABASE_SERVICE_ROLE_KEY mancanti."
    )

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY
)

BUCKET_NAME = "documents"


def get_document(document_id: str):

    response = (
        supabase.table("documents")
        .select("*")
        .eq("id", document_id)
        .limit(1)
        .execute()
    )

    if not response.data:
        return None

    return response.data[0]


def get_file_path(document: dict):

    file_path = document.get("file_path")

    if file_path:
        return file_path

    title = document.get("title")

    if title and title.lower().endswith(".pdf"):
        return title

    return None


def debug_evidence():

    response = (
        supabase.table("evidence")
        .select(
            "id, code, document_id, "
            "page_reference, source_excerpt, "
            "objective_information, element, "
            "review_status"
        )
        .order("created_at", desc=True)
        .limit(30)
        .execute()
    )

    if not response.data:

        print("Nessuna evidence presente.")
        return

    for evidence in response.data:

        document_id = evidence.get(
            "document_id"
        )

        if not document_id:
            continue

        document = get_document(
            document_id
        )

        if not document:
            print(
                f"[WARN] Documento non trovato: "
                f"{document_id}"
            )
            continue

        file_path = get_file_path(
            document
        )

        if not file_path:
            print(
                f"[WARN] Nessun file associabile "
                f"al documento {document_id}"
            )
            continue

        page_reference = evidence.get(
            "page_reference"
        )

        print("\n" + "=" * 80)
        print(
            f"EVIDENCE: "
            f"{evidence.get('code') or evidence.get('id')}"
        )
        print(f"FILE: {file_path}")
        print(f"PAGINA: {page_reference}")
        print(f"ELEMENTO: {evidence.get('element')}")
        print(
            f"STATUS: {evidence.get('review_status')}"
        )

        print("\nESTRATTO SALVATO:")
        print(
            evidence.get("source_excerpt")
            or "[vuoto]"
        )

        try:

            file_bytes = (
                supabase.storage
                .from_(BUCKET_NAME)
                .download(file_path)
            )

            reader = PdfReader(
                BytesIO(file_bytes)
            )

            try:
                page_number = int(
                    page_reference
                )
            except (TypeError, ValueError):

                print(
                    "\n[WARN] page_reference "
                    "non convertibile in numero."
                )

                continue

            index = page_number - 1

            if (
                index < 0
                or index >= len(reader.pages)
            ):
                print(
                    "\n[WARN] Pagina fuori "
                    "dall'intervallo del PDF."
                )
                continue

            page_text = (
                reader.pages[index]
                .extract_text()
                or ""
            )

            print(
                "\nTESTO ESTRATTO DAL PDF:"
            )

            print(
                page_text[:1500]
                .replace("\n", " ")
            )

        except Exception as exc:

            print(
                f"[ERRORE] "
                f"Impossibile verificare "
                f"{file_path}: {exc}"
            )


if __name__ == "__main__":
    debug_evidence()
