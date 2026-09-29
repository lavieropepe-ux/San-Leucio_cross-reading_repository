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
        "SUPABASE_URL / "
        "SUPABASE_SERVICE_ROLE_KEY mancanti."
    )

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY
)

BUCKET_NAME = "documents"


def list_all_files_in_bucket(
    path: str = ""
) -> list[str]:

    files = []

    items = (
        supabase.storage
        .from_(BUCKET_NAME)
        .list(path)
    )

    for item in items:

        name = item.get("name")

        if not name:
            continue

        item_path = (
            f"{path}/{name}"
            if path
            else name
        )

        if item.get("id") is None:

            files.extend(
                list_all_files_in_bucket(
                    item_path
                )
            )

        else:

            files.append(
                item_path
            )

    return files


def read_pdf_pages(
    file_path: str
) -> list[dict]:

    file_bytes = (
        supabase.storage
        .from_(BUCKET_NAME)
        .download(file_path)
    )

    reader = PdfReader(
        BytesIO(file_bytes)
    )

    pages = []

    for index, page in enumerate(
        reader.pages
    ):

        text = (
            page.extract_text()
            or ""
        )

        pages.append(
            {
                "page_number":
                    index + 1,

                "text":
                    text.strip(),

                "characters":
                    len(text),
            }
        )

    return pages


def main():

    print(
        f"=== Esplorazione bucket "
        f"'{BUCKET_NAME}' ==="
    )

    all_files = list_all_files_in_bucket()

    if not all_files:
        print(
            "Nessun file trovato "
            "nel bucket."
        )
        return

    print(
        f"Trovati {len(all_files)} "
        f"file totali.\n"
    )

    pdf_count = 0

    for file_path in all_files:

        if not file_path.lower().endswith(
            ".pdf"
        ):
            print(
                f"-> Ignorato: "
                f"{file_path}"
            )
            continue

        pdf_count += 1

        print(
            f"\n[{pdf_count}] "
            f"{file_path}"
        )

        try:

            pages = read_pdf_pages(
                file_path
            )

            native_pages = [
                page
                for page in pages
                if page["text"]
            ]

            empty_pages = [
                page
                for page in pages
                if not page["text"]
            ]

            print(
                f"   Pagine totali: "
                f"{len(pages)}"
            )

            print(
                f"   Pagine con testo: "
                f"{len(native_pages)}"
            )

            print(
                f"   Pagine senza testo: "
                f"{len(empty_pages)}"
            )

            total_chars = sum(
                page["characters"]
                for page in pages
            )

            print(
                f"   Caratteri estratti: "
                f"{total_chars}"
            )

            if native_pages:

                first_page = native_pages[0]

                preview = (
                    first_page["text"][:500]
                    .replace("\n", " ")
                )

                print(
                    f"   Prima pagina "
                    f"con testo: "
                    f"{first_page['page_number']}"
                )

                print(
                    f"   Anteprima:\n"
                    f"   {preview}..."
                )

            if empty_pages:

                empty_numbers = [
                    str(page["page_number"])
                    for page in empty_pages
                ]

                print(
                    "   Possibili scansioni/"
                    "immagini alle pagine: "
                    + ", ".join(
                        empty_numbers[:20]
                    )
                )

        except Exception as exc:

            print(
                f"   [ERRORE] "
                f"{exc}"
            )

    print(
        f"\nElaborazione completata. "
        f"Letti {pdf_count} PDF."
    )


if __name__ == "__main__":
    main()
