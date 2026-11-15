# GlyCadence Research Datasets — Data Dictionary, Access, Licensing & Provenance

> [!IMPORTANT]
> **Commercial & Research License Boundaries:** Open access on Figshare or PhysioNet is **never** treated as permission for unrestricted commercial use, and a repository dataset license is **never** stored as individual participant consent (`patients.consent_version`).
> - **ShanghaiT2DM:** Licensed under **CC BY 4.0** (`https://creativecommons.org/licenses/by/4.0/`, requires full attribution to Zhao et al., *Scientific Data* 2023).
> - **CGMacros v1.0.0:** Official PhysioNet DOI **`10.13026/3z8q-x658`** (`https://physionet.org/content/cgmacros/1.0.0/`), licensed under **CC BY-NC-SA 4.0** (`https://creativecommons.org/licenses/by-nc-sa/4.0/`, Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International) — **strictly Non-Commercial** and ShareAlike.
> - Raw research participant datasets in `datasets/raw/` are git-ignored and must never be committed to version control.

---

## 1. Checksum, Licensing vs. Consent & Provenance Immutability (`dataset_imports`)

### A. Separation of Dataset Licensing from Patient Consent
- **`dataset_imports.license_identifier` / `dataset_doi` / `dataset_version` / `source_url` / `license_url`:** Record the repository-level dataset license and citation provenance for an import batch.
- **`patients.consent_granted` & `patients.consent_version`:** Reserved strictly for individual participant-facing consent records. Importing a research dataset sets `consent_granted = FALSE` and `consent_version = NULL` unless verified participant-level consent documentation is explicitly provided. Repository license identifiers (such as `CC BY 4.0` or `CC BY-NC-SA 4.0`) are **never** written into `patients.consent_version`.

### B. Three Distinct Checksum Semantics
GlyCadence strictly separates regular-file byte hashes, directory manifest hashes, and structured in-memory payload hashes:
1. **`source_file_checksum` (`VARCHAR(64)`, nullable):** SHA-256 hex digest computed strictly from the **original on-disk bytes of a single regular file** (`compute_source_file_checksum(path)`). Passing a directory path raises `ValueError`. When ingestion is invoked with an in-memory `list[dict]` or a directory path rather than a single regular file, `source_file_checksum` is `NULL`.
2. **`directory_manifest_checksum` (`VARCHAR(64)`, nullable):** SHA-256 hex digest computed by `compute_directory_manifest_checksum(directory)` over the sorted relative file paths and raw file bytes of a multi-file dataset directory. Stored in `dataset_imports.directory_manifest_checksum` and **never** conflated with `source_file_checksum`.
3. **`input_payload_checksum` (`VARCHAR(64)`, nullable):** SHA-256 hex digest of a canonical UTF-8 JSON serialization (`json.dumps(..., sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)`) of structured input records (`compute_input_payload_checksum(payload)`).
   - **Canonicalization & Row-Order Contract:** Dictionary keys at every nesting level are sorted lexicographically (`sort_keys=True`), `datetime`/`date` values are formatted via ISO-8601 `.isoformat()`, `NaN`/`Infinity` values are normalized to `null` (`None`), and Unicode characters are preserved in UTF-8. **List/row sequence order is intentionally significant** (reordering input rows produces a different `input_payload_checksum` so input sequence mutations are detectable).
- **Database Constraint (`ck_dataset_imports_checksum_present`):** Enforces `source_file_checksum IS NOT NULL OR directory_manifest_checksum IS NOT NULL OR input_payload_checksum IS NOT NULL` alongside `preprocessing_version` and `license_identifier`.

### C. Immutability of Completed `dataset_imports` Provenance
- Enforced at the PostgreSQL database layer by trigger `trg_dataset_imports_protect_completed_provenance` (`protect_completed_dataset_import_provenance()`):
  - While `status = 'running'`, an import job may transition to `status = 'completed'` or `'failed'` and finalize its record counts.
  - Once `status = 'completed'`, any `DELETE` on the row or any `UPDATE` to `dataset_name`, `dataset_version`, `dataset_doi`, `source_url`, `license_identifier`, `license_url`, `source_file_checksum`, `directory_manifest_checksum`, `input_payload_checksum`, `preprocessing_version`, or `status` is blocked by PostgreSQL (`RAISE EXCEPTION`).

---

## 2. ShanghaiT2DM (`shanghai_t2dm`)

### Official Access, Figshare Item/Collection Version Verification & License Evidence
- **Publication:** Zhao, Q., Zhu, J., Shen, X., Lin, C., Zhang, Y., Liang, Y., Cao, B., Li, J., Liu, X., Rao, W., & Wang, C. *Chinese diabetes datasets for data-driven machine learning.* **Scientific Data** 10, 35 (2023). DOI: `https://doi.org/10.1038/s41597-023-01940-7`
- **Official Figshare Metadata (Verified via Figshare REST API v2):**
  1. **Primary Figshare Dataset Item (`20444397`, Version `1` — Default Reference Target):**
     - **Title:** *Diabetes Datasets-ShanghaiT1DM and ShanghaiT2DM*
     - **Versioned Item DOI:** `10.6084/m9.figshare.20444397.v1` (`https://doi.org/10.6084/m9.figshare.20444397.v1`)
     - **Published Date:** `2022-08-06T03:06:12Z`
     - **Archive File & Download URL:** `Diabetes_dataset.zip` (`https://ndownloader.figshare.com/files/36582306`, size `4,117,909` bytes, Figshare MD5 `ef6531d11f9ba26e88c387ecb2e47fa9`)
     - **License:** **`CC BY 4.0`** (`https://creativecommons.org/licenses/by/4.0/`)
  2. **Associated Figshare Collection (`6310860`) & Linked Multi-Version Item (`21600933`):**
     - **Collection Title:** *Chinese diabetes datasets for data-driven machine learning*
     - **Collection DOIs:** Version 1: `10.6084/m9.figshare.c.6310860.v1` (`2023-01-12`); Version 2: `10.6084/m9.figshare.c.6310860.v2` (`2023-03-21`)
     - **Linked Item `21600933` (*diabetes_datasets.zip*):**
       - Version 1 (`10.6084/m9.figshare.21600933.v1`, `2023-01-12`): `diabetes_datasets.zip` (`https://ndownloader.figshare.com/files/38283708`, Figshare MD5 `01fd2deaf16a41aa095ff46f8d900b67`, license `CC BY 4.0`).
       - Version 5 (`10.6084/m9.figshare.21600933.v5`, `2023-03-21`): `diabetes_datasets.zip` (`https://ndownloader.figshare.com/files/42966622`, Figshare MD5 `4bfb61cfa506b48155fd9e841ee48e21`, license `CC BY 4.0`).
  - **GlyCadence Provenance Pinning:** `ingest_shanghai_t2dm_records()` defaults to pinning `dataset_version = 'figshare-item-20444397-v1'`, `dataset_doi = '10.6084/m9.figshare.20444397.v1'`, `source_url = 'https://ndownloader.figshare.com/files/36582306'`, `license_identifier = 'CC BY 4.0'`, and `license_url = 'https://creativecommons.org/licenses/by/4.0/'` (and accepts explicit overrides if importing from `21600933.v1` or `21600933.v5`).

### Cohort, Sampling & Timezone Basis Semantics
- **Participants:** 100 Type 2 Diabetes Mellitus (`diabetes_type = 'T2D'`) patients in Shanghai, China (`Shanghai_T2DM/` directory + `Shanghai_T2DM_Summary.xlsx`). Any `ShanghaiT1DM` (`T1D`) records are strictly rejected (`t1d_cohort_mixing_forbidden`).
- **Primary CGM Sensor:** Abbott **FreeStyle Libre H** (`device_id = 'FreeStyle_Libre_H'`, `sampling_interval_min = 15`).
- **Observation Provenance:** `observation_provenance = 'native'` when `source_verified_native_export=True` (verified ShanghaiT2DM clinical workbooks recording direct 15-minute FreeStyle Libre H sensor reads) or when explicitly tagged on the row; otherwise `'unknown'`.
- **Timestamp Semantics & Timezone Basis (`timezone_basis`):**
  - Raw ShanghaiT2DM spreadsheet `Date` cells are naive local timestamps (e.g., `2021-09-13 08:00:00`) without an embedded UTC offset string.
  - Rather than claiming `UTC+08:00` is source-confirmed in the cell text, GlyCadence parses naive ShanghaiT2DM timestamps using IANA timezone `ZoneInfo("Asia/Shanghai")`, preserves the verbatim string in `raw_timestamp`, sets `timestamp_semantics = 'real_world_local'`, and records **`timezone_basis = 'assumed_study_location'`**.
  - Only timestamps that carry an explicit offset in the source string (e.g., `+08:00`) receive `timezone_basis = 'source_confirmed'`. If `assumed_iana_tz=None` is passed for a naive timestamp, `timezone_basis = 'unknown'` is recorded.
  - Analytics computed over records with `timezone_basis IN ('assumed_study_location', 'unknown')` automatically append an explicit uncertainty note to `uncertainty_notes`.

### Medication Provenance & Deduplication Rules (`ShanghaiT2DM`)
1. **Static Summary Regimens (`Shanghai_T2DM_Summary.xlsx`):** Medication columns in the summary table (`Hypoglycemic Agents`, `Insulin`) describe baseline prescribed regimens only. They create `medications` regimen rows and **never** generate `medication_events`.
2. **Timestamped Clinical Notations (`Shanghai_T2DM/*.xlsx`):**
   - `medication_events` (`status = 'unknown'`, `event_source = 'clinical_record'`) are created **only** when a specific time-series row contains a non-empty medication notation at that timestamp, preserving `source_sheet`, `source_cell_ref`, `recorded_at`, and exact `notes` text (`taken` or `missed` is never inferred).
   - **Fill-Down Suppression vs. Genuine Separate Administrations:**
     - Spreadsheet fill-down artifacts — rows explicitly flagged `is_fill_down = True` or identical medication text repeated across immediately contiguous 15-minute CGM rows ($\Delta t \le 15\text{ min}$) within the same sheet — are suppressed so copied cells do not fabricate duplicate `unknown` events.
     - Genuine separate timestamped administrations on the same day or across days (for example, morning `08:00` `"Metformin 0.5g"` and evening `20:00` `"Metformin 0.5g"`, where $\Delta t > 15\text{ min}$ or `is_fill_down = False`) are **both preserved** as distinct `MedicationEvent` rows with their respective timestamps, `source_sheet`, and `source_cell_ref`.

---

## 3. CGMacros (`cgmacros`)

### Official Access, DOI, Version & License Evidence
- **Title:** *CGMacros: a scientific dataset for personalized nutrition and diet monitoring* (Gutierrez-Osuna, R., Kerr, D., Mortazavi, B., Das, A., et al.)
- **Repository & Version:** PhysioNet, Version **`1.0.0`**
- **Official PhysioNet v1.0.0 DOI:** **`10.13026/3z8q-x658`** (`https://doi.org/10.13026/3z8q-x658`)
- **Official Source URL:** `https://physionet.org/content/cgmacros/1.0.0/`
- **Official License:** Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International Public License (**`CC BY-NC-SA 4.0`**, `https://creativecommons.org/licenses/by-nc-sa/4.0/`)
  - **Non-Commercial Restriction:** Use of CGMacros data is restricted to non-commercial research and evaluation under `CC BY-NC-SA 4.0`. Open access on PhysioNet does **not** permit commercial deployment or commercial redistribution.
- **GlyCadence Provenance Pinning:** `dataset_version = 'physionet-cgmacros-v1.0.0'`, `dataset_doi = '10.13026/3z8q-x658'`, `source_url = 'https://physionet.org/content/cgmacros/1.0.0/'`, `license_identifier = 'CC BY-NC-SA 4.0'`, `license_url = 'https://creativecommons.org/licenses/by-nc-sa/4.0/'`. Individual `Patient` rows have `consent_granted = FALSE` and `consent_version = NULL`.

### Strict T2D Separation Rules
- **Total Participants in Archive:** 45 adults (`bio.csv` `A1c PDL (Lab)`):
  - **14 Type 2 Diabetes (`diabetes_type = 'T2D'`):** `HbA1c > 6.4%`
  - **16 Prediabetes (`diabetes_type = 'prediabetes'`):** `5.7% <= HbA1c <= 6.4%`
  - **15 Healthy (`diabetes_type = 'healthy'`):** `HbA1c < 5.7%`
- Only the **14 T2D participants** are ingested when `t2d_only=True` (default for T2D-specific analysis).

### Timestamp Semantics (`date_shifted_relative`)
- Per the official PhysioNet CGMacros `DataDictionary`, `Timestamp` is defined as:
  > *"Randomly shifted time stamps for days in the study that provide the incremental time stamp the CGM readings occurred."*
- **GlyCadence Handling:**
  1. Preserves the exact supplied string in `raw_timestamp`.
  2. Marks `timestamp_semantics = 'date_shifted_relative'` and `timezone_basis = 'not_applicable_relative'` on all CGMacros `glucose_readings` and `meals`.
  3. Does **not** infer a real-world geographic timezone (stores timestamps against a neutral `+00:00` reference epoch purely to preserve exact within-participant elapsed intervals $\Delta t$ and chronological ordering).
  4. **Blocks Cross-Dataset / Cross-Participant Calendar-Date Alignment:** `validate_calendar_date_comparability()` raises `ValueError("calendar_date_comparison_forbidden_for_date_shifted_relative")` if code attempts to compare or align calendar dates across records where `timestamp_semantics == 'date_shifted_relative'`.
  5. **Evidence Labeling:** Analytics computed over `date_shifted_relative` records automatically include an explicit `uncertainty_notes` item documenting that calendar dates are randomly shifted and valid only for within-participant relative elapsed-time analysis.

### Tightened Native CGM Observation Provenance (`native` | `interpolated` | `derived` | `unknown`)
- Participants wore two blinded sensors simultaneously:
  - **Abbott FreeStyle Libre Pro (`Libre GL`):** Nominal sensor capture interval = **15 minutes** (`device_id = 'FreeStyle_Libre_Pro'`, `sampling_interval_min = 15`).
  - **Dexcom G6 Pro (`Dexcom GL`):** Nominal sensor capture interval = **5 minutes** (`device_id = 'Dexcom_G6_Pro'`, `sampling_interval_min = 5`).
- **Why Both Periodic Subsampling AND Interval-Spacing Inference Are Invalid:**
  - The published PhysioNet CGMacros participant CSV files (`CGMacros-XXX.csv`) provide 1-minute aligned rows without an explicit indicator column stating which rows were original sensor captures versus linearly interpolated values.
  - Selecting every 5th or 15th row — **or classifying a subset of rows as `native` merely because their timestamps happen to be spaced 5 or 15 minutes apart** — cannot verify that those timestamps match the true physical sensor capture phase rather than an arbitrary 5- or 15-minute slice of an interpolated grid.
- **GlyCadence Provenance Rules:**
  - Every `GlucoseReading` carries `observation_provenance IN ('native', 'interpolated', 'derived', 'unknown')`:
    - `'native'`: Assigned **only** when verifiable source evidence exists — either an explicit row-level provenance tag (`libre_provenance='native'` / `dexcom_provenance='native'` / `observation_provenance='native'`) or `source_verified_native_export=True` for an authenticated raw sensor export.
    - `'interpolated'`: Row explicitly marked as linearly interpolated between sensor captures.
    - `'derived'`: Value mathematically derived/aggregated from multiple readings.
    - `'unknown'`: Default for all CGMacros CSV rows (including 1-minute aligned rows AND any 5- or 15-minute spaced rows that lack explicit source provenance verification).
  - **Analytics Gate (`native_only=True` by default for native-cadence CGM analytics):**
    - Only verified `'native'` readings enter native-cadence CGM coverage and summary analytics when `native_only=True`.
    - Regularly spaced (`5 min` or `15 min`) CGMacros readings without verified provenance remain `'unknown'` and are **excluded** when `native_only=True`.
    - Observations with `'interpolated'`, `'derived'`, or `'unknown'` provenance are counted and reported transparently (`native_observation_count`, `interpolated_observation_count`, `derived_observation_count`, `unknown_observation_count`) and excluded from native-cadence metrics unless `include_non_native=True` is explicitly requested for exploratory comparison.
