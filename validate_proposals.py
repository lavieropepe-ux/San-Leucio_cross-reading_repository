name: Promuovi proposte verificate San Leucio

on:
  workflow_dispatch:

jobs:
  validate-proposals:

    runs-on: ubuntu-latest

    steps:

      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Configura Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.10"

      - name: Installa dipendenze
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Promuovi solo conoscenza verificata
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
        run: python validate_proposals.py
