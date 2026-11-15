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
- **Official Figshare Metadata (Verified via Figshare REST API v2 — committed verbatim in `docs/provenance/figshare_20444397_v1.json`, `v2.json`, and `v3.json`):**
  1. **Canonical Release — Figshare Dataset Item (`20444397`, Version `3` — Default Archive Pipeline Target):**
     - **Canonical Status:** **`v3` (`data.zip`, `10.6084/m9.figshare.20444397.v3`) is the canonical ShanghaiT2DM dataset for GlyCadence**, matching the published 2023 *Scientific Data* paper (Zhao et al., 2023: 100 unique T2D patients across 109 hospital admissions).
     - **Versioned Item DOI:** `10.6084/m9.figshare.20444397.v3` (`https://doi.org/10.6084/m9.figshare.20444397.v3`)
     - **API Timestamps (`figshare_20444397_v3.json`):** `created_date: "2022-11-20T07:14:35Z"`, `published_date: "2022-11-20T07:14:35Z"`, `modified_date: "2022-11-20T07:14:36Z"`
     - **Archive File & Download URL:** `data.zip` (Figshare file ID `38259264`, `https://ndownloader.figshare.com/files/38259264`, exact byte size **`3,418,039` bytes** (`"size": 3418039`), `supplied_md5` / `computed_md5`: `ecadc819dd20aeb92d60ce41ceb16fd2`, verified on-disk SHA-256: `5ea3d97d189edc38de69a73ab5a7b653085c5cda4691b2eabe2a474295e0d05e`)
     - **Contents of `data.zip` (v3):** `Shanghai_T2DM_Summary.xlsx` (sheet `'T2DM'`, 109 rows across 100 unique T2D participants) + 109 workbooks (`Shanghai_T2DM/2000_0_20201230.xlsx` .. `2099_0_20201116.xls`, 20 `.xlsx` + 89 `.xls`).
     - **License:** **`CC BY 4.0`** (`https://creativecommons.org/licenses/by/4.0/`)
  2. **Legacy Pre-Publication Release — Figshare Dataset Item (`20444397`, Version `1` — Excluded from Default Pipelines):**
     - **Exclusion Policy:** **`v1` (`Diabetes_dataset.zip`) is excluded from default archive ingestion pipelines** (`ingest_shanghai_t2dm_archive()` and `python -m app.ingestion.run --dataset shanghai` default to `v3` `10.6084/m9.figshare.20444397.v3`) so `v1` and `v3` are never mixed in the same default cohort. `v1` is retained in documentation and provenance audit logs for historical reproducibility only and requires explicit `--dataset-version figshare-item-20444397-v1` override to ingest.
     - **Title:** *Diabetes Datasets-ShanghaiT1DM and ShanghaiT2DM*
     - **Versioned Item DOI:** `10.6084/m9.figshare.20444397.v1` (`https://doi.org/10.6084/m9.figshare.20444397.v1`)
     - **API Timestamps (`figshare_20444397_v1.json`):** `created_date: "2022-08-06T16:25:02Z"`, `published_date: "2022-08-06T16:25:02Z"`, `modified_date: "2022-11-20T07:14:35Z"`
     - **Archive File & Download URL:** `Diabetes_dataset.zip` (Figshare file ID `36582306`, `https://ndownloader.figshare.com/files/36582306`, exact byte size **`732,371` bytes** (`"size": 732371`), `supplied_md5` / `computed_md5`: `ef6531d11f9ba26e88c387ecb2e47fa9`, verified on-disk SHA-256: `f42ceec19b95010c15aa8fa7b0a9d9a3e1a0977680ee8f1089145e81b6ca2b67`)
     - **Contents of `Diabetes_dataset.zip` (v1):** `ShanghaiT2DM.xlsx` (86 T2DM rows across 2 sheets: `'Sheet1'` in Chinese and `'翻译后'` in English) + 90 CSV files (`ShanghaiT2DM/1018_0.csv` .. `ShanghaiT2DM/1110_1.csv`, 84 unique participant IDs).
     - **License:** **`CC BY 4.0`** (`https://creativecommons.org/licenses/by/4.0/`)
  3. **Associated Figshare Collection (`6310860`):**
     - **Collection Title:** *Chinese diabetes datasets for data-driven machine learning*
     - **Collection DOIs:** Version 1: `10.6084/m9.figshare.c.6310860.v1` (`2023-01-12`); Version 2: `10.6084/m9.figshare.c.6310860.v2` (`2023-03-21`)
  - **GlyCadence Provenance Pinning:** `ingest_shanghai_t2dm_archive()` and the CLI (`python -m app.ingestion.run --dataset shanghai`) default to pinning the canonical **v3** metadata (`dataset_version = 'figshare-item-20444397-v3'`, `dataset_doi = '10.6084/m9.figshare.20444397.v3'`, `source_url = 'https://ndownloader.figshare.com/files/38259264'`, `license_identifier = 'CC BY 4.0'`, `license_url = 'https://creativecommons.org/licenses/by/4.0/'`).

### Cohort, Sampling & Timezone Basis Semantics
- **Participants:** 86 T2D participants (90 admissions) in v1 (`Diabetes_dataset.zip`) and 100 T2D participants (109 admissions) in v3 (`data.zip`). Any `ShanghaiT1DM` (`T1D`) records are strictly rejected (`t1d_cohort_mixing_forbidden`).
- **Primary CGM Sensor:** Abbott **FreeStyle Libre H** (`device_id = 'FreeStyle_Libre_H'`, `sampling_interval_min = 15`).
- **Observation Provenance:** `observation_provenance` defaults to `'unknown'` (`source_verified_native_export=False` by default). Setting `source_verified_native_export=True` requires a non-empty `native_evidence_reference` citation stored in `dataset_imports.quality_report_summary["native_evidence_reference"]` and `audit_logs`. CBG (`reading_type = 'cbg'`) rows are never stamped as `'native'` CGM.
- **Timestamp Semantics & Timezone Basis (`timezone_basis`) — Sources Checked:**
  - We inspected three primary sources for explicit timezone documentation:
    1. **Dataset Paper (Zhao et al., *Scientific Data* 10, 35, 2023, `10.1038/s41597-023-01940-7`):** States that clinical recruitment and CGM monitoring took place at Shanghai Sixth People's Hospital and Shanghai Fourth People's Hospital (Shanghai, China) and documents the timestamp column format (`YYYY:MM:DD hh:mm:ss`) without stating an explicit UTC offset or IANA timezone string.
    2. **Figshare Metadata (`docs/provenance/figshare_20444397_v1.json` & `v3.json`):** The `description` field states `<p>These two datasets from Type 1 Diabetes and Type 2 Diabetes patients in Shanghai, China.</p>` and contains no timezone field.
    3. **Workbook & CSV Headers/Cells (`ShanghaiT2DM/*.csv` and `Shanghai_T2DM/*.xls*`):** Column headers (`time`, `record time`, `Date`) and cell values (`2021/4/20 11:33`, `2020-12-30 13:54:00`) are naive local timestamps with no embedded UTC offset.
  - Because the timezone is inferred from the hospital study location (`Shanghai, China`) rather than explicitly encoded in the timestamps or data dictionary, GlyCadence parses naive ShanghaiT2DM timestamps using `ZoneInfo("Asia/Shanghai")` (`UTC+08:00`), preserves the verbatim string in `raw_timestamp`, sets `timestamp_semantics = 'real_world_local'`, and records **`timezone_basis = 'assumed_study_location'`**.
  - Only timestamps carrying an explicit offset in the source string (e.g., `+08:00`) receive `timezone_basis = 'source_confirmed'`.

### Medication Provenance Rules (`ShanghaiT2DM`)
1. **Static Summary Regimens (`ShanghaiT2DM.xlsx` / `Shanghai_T2DM_Summary.xlsx`):** Medication columns in the summary table (`Diabetes medication`, `Hypoglycemic Agents`, `Insulin`) describe baseline prescribed regimens only. They create `medications` regimen rows and **never** generate `medication_events`.
2. **Timestamped Clinical Notations (`ShanghaiT2DM/*.csv` / `Shanghai_T2DM/*.xls*`):**
   - `medication_events` (`status = 'unknown'`, `event_source = 'clinical_record'`) are created for every non-empty time-series medication cell at that row's timestamp (`taken` or `missed` is never inferred).
   - **Real Sheet & Cell Provenance (No Fabricated References):**
     - When ingested from an Excel workbook (`.xlsx` / `.xls`), all sheets in the workbook are read (`pd.read_excel(path, sheet_name=None)`), recording the real Excel sheet name in `source_sheet` and the real 1-based Excel cell coordinate (e.g. `G14`, `H22`) in `source_cell_ref`.
     - When ingested from a CSV file or in-memory dict where no sheet name or cell reference exists, `source_sheet` and `source_cell_ref` are stored as `NULL` (`None`) — never fabricated as `_Sheet1` or `G{idx+2}`.
   - **Real-Archive Inspection of Fill-Down:** Inspection of all 109 workbooks in `data.zip` (4,372 medication rows) and all 90 CSVs in `Diabetes_dataset.zip` confirmed `0` contiguous fill-down rows; every non-empty medication row in the archive is a distinct timestamped clinical notation and is preserved without heuristic suppression.

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
