# Input handling

The private working package includes the original raw CSVs and form workbooks, plus the assessment brief, SOPs and paper in `reference/`. They are never overwritten by notebook runs. `input_manifest.csv` records SHA-256 fingerprints for supplied inputs and reference files.

If distributing the repository without raw inputs, provide authorized recipients with the same input files separately and preserve their filenames in `data/raw/`. Do not substitute edited exports without recording a new input version and rerunning both notebooks. Raw and reference files are ignored by Git by default; confirm publication permissions before changing that choice.
