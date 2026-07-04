"""ETL package for the E-Commerce Data Pipeline.

Contains the four-stage pipeline modules:
    - extract   : pull raw data from CSV / Excel / simulated API
    - transform : clean, validate, enrich
    - load      : persist into PostgreSQL (dev) and SQLite (deploy)
    - pipeline  : orchestrate the full ETL run
"""
