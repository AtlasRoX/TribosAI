# Tribos data directory

> **Tribos**: a research partner for engineering, physics and mathematics
> **Made by ChronoStrider Engineering**

This is the default root for dataset paths typed into a question (for example "fit the model to
`data/run_03.csv`"); `TRIBOS_DATASET_ROOTS` overrides it, see `tribos/datasets/paths.py`. Files uploaded in the app
are kept in the per-user upload store, not here.

Supported dataset formats: CSV, TSV, XLSX, HDF5, MAT and Parquet. The app's local state subfolders here (`jobs/`,
`router/`, `feedback/`, `files/`) are ignored by git; keep large datasets out of the repository as well.
