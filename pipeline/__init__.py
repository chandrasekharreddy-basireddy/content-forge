"""Content Forge: a document-to-content pipeline built on Sarvam.

The package is deliberately flat. Read in this order:

    config.py    every setting, in one place
    llm.py       the only file that talks to Sarvam
    ingest.py    file in, clean text and chunks out
    schemas.py   the contract for each output type
    agents.py    extract, plan, write, critique - four functions
    runner.py    the loop that strings them together
    store.py     SQLite, with an optional Supabase copy
    exports.py   objects out as md, docx, pptx, csv, json
"""

__version__ = "1.0.0"
