# GlyCadence Research Datasets — Data Dictionary, Access, Licensing & Provenance

> [!IMPORTANT]
> **Commercial & Research License Boundaries:** Open access on Figshare or PhysioNet is **never** treated as permission for unrestricted commercial use.
> - **ShanghaiT2DM:** Licensed under **CC BY 4.0** (requires full attribution to Zhao et al., *Scientific Data* 2023).
> - **CGMacros v1.0.0:** Licensed under **CC BY-NC-SA 4.0** (Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International) — **strictly Non-Commercial** and ShareAlike.
> - Raw research participant datasets in `datasets/raw/` are git-ignored and must never be committed to version control.

---

## 1. Checksum & Provenance Semantics (`dataset_imports`)

GlyCadence strictly distinguishes between original file-byte checksums and structured in-memory payload checksums:
- **`source_file_checksum` (`VARCHAR(64)`, nullable):** SHA-256 hex digest computed strictly from the **original on-disk file bytes** (`compute_source_file_checksum(path)`). When ingestion is invoked with an in-memory `DataFrame` or `list[dict]` rather than an on-disk file, `source_file_checksum` is explicitly `NULL` — a DataFrame serialization hash is **never** labeled as `source_file_checksum`.
- **`input_payload_checksum` (`VARCHAR(64)`, nullable):** SHA-256 hex digest of a documented canonical UTF-8 JSON serialization (`sort_keys=True, separators=(',', ':')`) of structured input records (`compute_input_payload_checksum(payload)`).
- **Database Constraint (`ck_dataset_imports_checksum_present`):** Enforces `source_file_checksum IS NOT NULL OR input_payload_checksum IS NOT NULL` alongside `preprocessing_version` and `license_identifier`.

---

## 2. ShanghaiT2DM (`shanghai_t2dm`)

### Official Access, Item/Version & License Evidence
- **Publication:** Zhao, Q., Zhu, J., Shen, X., Lin, C., Zhang, Y., Liang, Y., Cao, B., Li, J., Liu, X., Rao, W., & Wang, C. *Chinese diabetes datasets for data-driven machine learning.* **Scientific Data** 10, 35 (2023). DOI: `https://doi.org/10.1038/s41597-023-01940-7`
- **Figshare Collection DOI:** `https://doi.org/10.6084/m9.figshare.c.6310860.v1` (Collection ID `6310860`, Version `1`)
- **Figshare Dataset Item DOI:** `https://doi.org/10.6084/m9.figshare.20444397.v1` (*Diabetes Datasets, ShanghaiT1DM and ShanghaiT2DM*, Version `1`)
- **License:** Creative Commons Attribution 4.0 International (**`CC BY 4.0`**)
- **GlyCadence Retention Policy:** `dataset_license_bound` (`consent_version = 'figshare-cc-by-4.0-v1'`)

### Cohort, Sampling & Timestamp Semantics
- **Participants:** 100 Type 2 Diabetes Mellitus (`diabetes_type = 'T2D'`) patients in Shanghai, China (`Shanghai_T2DM/` directory + `Shanghai_T2DM_Summary.xlsx`). Any `ShanghaiT1DM` (`T1D`) records are strictly rejected (`t1d_cohort_mixing_forbidden`).
- **Primary CGM Sensor:** Abbott **FreeStyle Libre H** (`device_id = 'FreeStyle_Libre_H'`, `sampling_interval_min = 15`).
- **Observation Provenance:** `observation_provenance = 'native'` (the participant Excel spreadsheets record the actual 15-minute FreeStyle Libre H sensor captures directly without 1-minute grid interpolation).
- **Timestamp Semantics:** `timestamp_semantics = 'real_world_local'` (clinical timestamps recorded in Shanghai local time `UTC+08:00`, preserved verbatim in `raw_timestamp` and normalized to UTC `recorded_at`).

### Medication Provenance Rules (`ShanghaiT2DM`)
1. **Static Summary Regimens (`Shanghai_T2DM_Summary.xlsx`):** Medication columns in the summary table (`Hypoglycemic Agents`, `Insulin`) describe baseline prescribed regimens only. They create `medications` regimen rows and **never** generate `medication_events`.
2. **Timestamped Clinical Notations (`Shanghai_T2DM/*.xlsx`):**
   - `medication_events` (`status = 'unknown'`, `event_source = 'clinical_record'`) are created **only** when a specific time-series row contains a genuine, non-empty medication administration notation at that timestamp.
   - Static regimen descriptions or consecutively repeated/copied identical medication strings across rows are deduplicated/suppressed so repeated `unknown` events are **never** fabricated from copied text.
   - Exact source text is preserved in `notes`; `taken` or `missed` status is **never** inferred.

---

## 3. CGMacros (`cgmacros`)

### Official Access, Version & License Evidence
- **Title:** *CGMacros: a scientific dataset for personalized nutrition and diet monitoring* (Gutierrez-Osuna, R., Kerr, D., Mortazavi, B., Das, A., et al.)
- **Repository & Version:** PhysioNet, Version **`1.0.0`** (`https://physionet.org/content/cgmacros/1.0.0/`, DOI: `https://doi.org/10.13026/3zdc-eb88`)
- **Official License:** Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International Public License (**`CC BY-NC-SA 4.0`**)
  - **Non-Commercial Restriction:** Use of CGMacros data is restricted to non-commercial research and evaluation under `CC BY-NC-SA 4.0`. Open access on PhysioNet does **not** permit commercial deployment or commercial redistribution.
- **GlyCadence Retention Policy:** `dataset_license_bound` (`consent_version = 'physionet-cc-by-nc-sa-4.0-v1.0.0'`, `license_identifier = 'CC BY-NC-SA 4.0'`)

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
  2. Marks `timestamp_semantics = 'date_shifted_relative'` on all CGMacros `glucose_readings` and `meals`.
  3. Does **not** infer a real-world geographic timezone (stores timestamps against a neutral `+00:00` reference epoch purely to preserve exact within-participant elapsed intervals $\Delta t$ and chronological ordering).
  4. **Blocks Cross-Dataset / Cross-Participant Calendar-Date Alignment:** `validate_calendar_date_comparability()` raises `ValueError("calendar_date_comparison_forbidden_for_date_shifted_relative")` if code attempts to compare or align calendar dates across records where `timestamp_semantics == 'date_shifted_relative'`.
  5. **Evidence Labeling:** Analytics computed over `date_shifted_relative` records automatically include an explicit `uncertainty_notes` item documenting that calendar dates are randomly shifted and valid only for within-participant relative elapsed-time analysis.

### Native CGM Observation Provenance (`native` | `interpolated` | `derived` | `unknown`)
- Participants wore two blinded sensors simultaneously:
  - **Abbott FreeStyle Libre Pro (`Libre GL`):** Native sensor capture interval = **15 minutes** (`device_id = 'FreeStyle_Libre_Pro'`, `sampling_interval_min = 15`).
  - **Dexcom G6 Pro (`Dexcom GL`):** Native sensor capture interval = **5 minutes** (`device_id = 'Dexcom_G6_Pro'`, `sampling_interval_min = 5`).
- **Why Periodic Subsampling (`every 5th` or `every 15th` row) Is Invalid:**
  - The published PhysioNet CGMacros participant CSV files (`CGMacros-XXX.csv`) provide 1-minute aligned rows without an explicit indicator column stating which 1-minute rows were original sensor captures versus linearly interpolated values, and sensor phase offsets can shift across sensor warm-ups or gaps.
  - Selecting every 5th or 15th row **cannot** verify that a row was a true sensor measurement.
- **GlyCadence Provenance Rules:**
  - Every `GlucoseReading` carries `observation_provenance IN ('native', 'interpolated', 'derived', 'unknown')`:
    - `'native'`: Verified raw sensor export or row carrying explicit source evidence (`libre_provenance='native'` / `dexcom_provenance='native'`, or unaligned raw sensor stream at native device intervals).
    - `'interpolated'`: Row explicitly marked or detected as linearly interpolated between sensor captures.
    - `'derived'`: Value mathematically derived/aggregated from multiple readings.
    - `'unknown'`: 1-minute aligned CGMacros CSV rows where native vs. interpolated status is not established in the source file.
  - **Analytics Gate (`native_only=True` by default for native-cadence CGM analytics):**
    - Only verified `'native'` readings enter native-cadence CGM coverage and summary analytics when `native_only=True`.
    - Observations with `'interpolated'`, `'derived'`, or `'unknown'` provenance are counted and reported transparently (`native_observation_count`, `interpolated_observation_count`, `derived_observation_count`, `unknown_observation_count`) and excluded from native-cadence metrics unless `include_non_native=True` is explicitly requested for exploratory comparison.
