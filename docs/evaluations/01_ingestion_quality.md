# Day 3 Evaluation Report — Real-Archive Ingestion Quality & Provenance Audit

**Date:** 2026-11-15  
**Preprocessing Version:** `v1.2.0`  
**Evaluation Scope:** End-to-end verification of `ingest_shanghai_t2dm_archive()` and `ingest_cgmacros_archive()` via `python -m app.ingestion.run` against the official downloaded archives on disk.

---

## 1. Reproducible CLI Commands

```powershell
# ShanghaiT2DM Figshare v1 (Diabetes_dataset.zip)
cd backend
.\.venv\Scripts\python.exe -m app.ingestion.run `
  --dataset shanghai `
  --archive ../datasets/raw/Diabetes_dataset.zip `
  --dataset-version figshare-item-20444397-v1 `
  --dataset-doi 10.6084/m9.figshare.20444397.v1 `
  --source-url https://ndownloader.figshare.com/files/36582306

# ShanghaiT2DM Figshare v3 (data.zip, Scientific Data 2023 release)
.\.venv\Scripts\python.exe -m app.ingestion.run `
  --dataset shanghai `
  --archive ../datasets/raw/Shanghai_data_v3.zip `
  --dataset-version figshare-item-20444397-v3 `
  --dataset-doi 10.6084/m9.figshare.20444397.v3 `
  --source-url https://ndownloader.figshare.com/files/38259264

# CGMacros PhysioNet v1.0.0 (T2D cohort, HbA1c > 6.4%)
.\.venv\Scripts\python.exe -m app.ingestion.run `
  --dataset cgmacros `
  --archive ../datasets/raw/CGMacros_csv_archive.zip
```

---

## 2. Official Source Provenance & Checksums

Verbatim Figshare REST API v2 metadata responses (`https://api.figshare.com/v2/articles/20444397/versions/{1,2,3}`) are committed under `docs/provenance/`:
- `docs/provenance/figshare_20444397_v1.json` (`Diabetes_dataset.zip`, file ID `36582306`, `732,371` bytes, MD5 `ef6531d11f9ba26e88c387ecb2e47fa9`, SHA-256 `f42ceec19b95010c15aa8fa7b0a9d9a3e1a0977680ee8f1089145e81b6ca2b67`, license `CC BY 4.0`).
- `docs/provenance/figshare_20444397_v2.json` (`Shanghai_T1DM.rar` + `Shanghai_T2DM.rar`, license `CC BY 4.0`).
- `docs/provenance/figshare_20444397_v3.json` (`data.zip`, file ID `38259264`, `3,418,039` bytes, MD5 `ecadc819dd20aeb92d60ce41ceb16fd2`, SHA-256 `5ea3d97d189edc38de69a73ab5a7b653085c5cda4691b2eabe2a474295e0d05e`, license `CC BY 4.0`).

---

## 3. Real-Archive Ingestion Counts

| Metric | ShanghaiT2DM v1 (`Diabetes_dataset.zip`) | ShanghaiT2DM v3 (`data.zip`) | CGMacros v1.0.0 (`t2d_only=True`) |
| :--- | ---: | ---: | ---: |
| **Archive SHA-256 (`source_file_checksum`)** | `f42ceec19b95010c15aa8fa7b0a9d9a3e1a0977680ee8f1089145e81b6ca2b67` | `5ea3d97d189edc38de69a73ab5a7b653085c5cda4691b2eabe2a474295e0d05e` | `be73e1d5a309e1f74f8d5dc4e9338b678196d8e05357171b668fd38b104d1dee` |
| **Canonical Payload SHA-256 (`input_payload_checksum`)** | `4415dcefa6f460713d392a3b16b1841c554eeb92ab7b198129124f22eda180be` | `91f4121b9b3b82170d2eac66be665a69dd1fbc9eb3f499b2499369a580a71101` | `6698ceb2d77b4491a7efdc8e1c7f8869e75707aa3d6fa3628d13478a226074b7` |
| **Archive Member Count** | 104 | 127 | 48 |
| **Total Workbook Sheets / CSVs Read** | 90 | 109 | 45 (`14` ingested, `31` excluded non-T2D) |
| **Unique T2D Participants Ingested** | 84 | 100 | 14 |
| **CGM Rows Ingested (`reading_type="cgm"`)** | 96,784 | 112,287 | 418,165 (`209,595` Libre + `208,570` Dexcom) |
| **CBG Rows Ingested (`reading_type="cbg"`)** | 2,007 | 3,261 | 0 |
| **Meals Ingested** | 2,640 | 3,060 | 455 |
| **Medication Regimens Ingested** | 550 (`84` summary + `466` timestamped) | 430 (`100` summary + `330` timestamped) | 0 |
| **Medication Events Ingested** | 1,968 | 2,993 | 0 |
| **Clinical Records Ingested** | 90 | 109 | 14 |
| **Activity Records Ingested** | 0 | 0 | 194,344 |
| **Total Records Accepted** | **104,039** | **122,140** | **612,978** |
| **Total Records Rejected** | **5,283** | **93** | **0** |
| **Provenance: `native`** | 0 | 0 | 0 |
| **Provenance: `interpolated`** | 0 | 0 | 0 |
| **Provenance: `derived`** | 0 | 0 | 0 |
| **Provenance: `unknown`** | 98,791 | 115,548 | 418,165 |
| **Timestamp Semantics** | `real_world_local` | `real_world_local` | `date_shifted_relative` |
| **Timezone Basis** | `assumed_study_location` | `assumed_study_location` | `not_applicable_relative` |

### 3.1 Exact Reconciliation of Per-Table Inserts & Rejections
- **ShanghaiT2DM v1 (`Diabetes_dataset.zip`):**
  - `96,784` (CGM) + `2,007` (CBG) + `2,640` (Meals) + `550` (Medication regimens: `84` from summary sheet + `466` novel regimens discovered in timestamped rows) + `1,968` (Medication events) + `90` (Clinical records) + `0` (Activity) = **`104,039` accepted records**.
  - Rejections: `5,255` (`invalid_timestamp`) + `27` (`invalid_glucose_number`) + `1` (`out_of_physiological_range`) = **`5,283` rejected records**.
  - `records_accepted + records_rejected` = `104,039 + 5,283` = **`109,322`**.
- **ShanghaiT2DM v3 (`data.zip`):**
  - `112,287` (CGM) + `3,261` (CBG) + `3,060` (Meals) + `430` (Medication regimens: `100` from summary sheet + `330` novel regimens discovered in timestamped rows) + `2,993` (Medication events) + `109` (Clinical records) + `0` (Activity) = **`122,140` accepted records**.
  - Rejections: `92` (`invalid_timestamp`) + `1` (`out_of_physiological_range`) = **`93` rejected records**.
  - `records_accepted + records_rejected` = `122,140 + 93` = **`122,233`**.
- **CGMacros v1.0.0 (`t2d_only=True`):**
  - `418,165` (CGM) + `0` (CBG) + `455` (Meals) + `0` (Medications) + `0` (Medication events) + `14` (Clinical records) + `194,344` (Activity) = **`612,978` accepted records**, **`0` rejected records**.

---

## 4. Rejection Breakdown & Real-Archive Discrepancies Discovered

### 4.1 ShanghaiT2DM Rejection Breakdown
- **v1 (`Diabetes_dataset.zip`):**
  - `invalid_timestamp`: `5,255` rows — trailing empty rows or formatting rows at the bottom of the 90 CSV files where the `Time` cell is blank (`NaN`).
  - `invalid_glucose_number`: `27` rows — non-numeric text annotations in glucose cells (e.g. `"ketone"`, `"--"` variants, or notes in `Capillary blood glucose`).
  - `out_of_physiological_range`: `1` row — a typo in `Capillary blood glucose` (`113.6 mmol/L` = `2,046.87 mg/dL` > `1,500.0 mg/dL`, likely intended as `11.36 mmol/L` or `113.6 mg/dL`).
- **v3 (`data.zip`):**
  - `invalid_timestamp`: `92` rows — trailing blank `NaT` timestamp rows at the end of Excel worksheets.
  - `out_of_physiological_range`: `1` row — the same physiological outlier (`2,044.8 mg/dL` > `1,500.0 mg/dL` in `CBG (mg / dl)`).

### 4.2 Discrepancies Found Between Documentation / Earlier Assumptions and Real Archives
1. **Figshare Item `20444397` Has 3 Distinct Versions:**
   - **v1 (`Diabetes_dataset.zip`, `732,371` bytes):** Initial 2022 submission containing 90 CSV files (`84` unique T2D participant IDs) and `ShanghaiT2DM.xlsx` (`86` rows across 2 sheets: `'Sheet1'` in Chinese and `'翻译后'` in English). In v1 CSVs, `'cgm'` is already in **`mg/dL`** (`39.6–468.0 mg/dL`), while `'Capillary blood glucose'` is in **`mmol/L`** (median `8.2 mmol/L`).
   - **v3 (`data.zip`, `3,418,039` bytes):** Published *Scientific Data* (2023) archive containing 109 Excel workbooks (`100` unique T2D participants `2000`–`2099`, with 9 follow-up admissions `_1`/`_2`) plus `Shanghai_T2DM_Summary.xlsx`. In v3 workbooks, both `'CGM (mg / dl)'` and `'CBG (mg / dl)'` are explicitly in **`mg/dL`**.
2. **Gender Coding (`Female=1, Male=2`):**
   - Both v1 (`性别（女1，男2）`) and v3 (`Gender (Female=1, Male=2)`) summary sheets encode `1 = female` and `2 = male`. Earlier ingestion code assumed ISO 5218 (`1 = male, 2 = female`); fixed in `_normalize_sex()`.
3. **Zero Adjacent Fill-Down Medication Artifacts in Real Archives:**
   - Direct inspection of all 109 Excel workbooks in v3 and all 90 CSVs in v1 confirmed **`0` adjacent duplicate medication rows**. Every repeated dose on the same day occurs ≥4 hours apart (legitimate multi-daily dosing such as TID/QID insulin or oral agents). The earlier 15-minute duplicate suppression heuristic and unrequested `is_fill_down` parameter have been removed.
4. **CGMacros `bio.csv` Anthropometric Units (`lbs` and `inches`):**
   - `DataDictionary_Bio.csv` in the official PhysioNet archive specifies `'Body weight '` is in **pounds (lbs)** (`116.8–284.6 lbs`) and `'Height '` is in **inches** (`59–72 in`). `ingest_cgmacros()` now converts `lbs -> kg` (`* 0.45359237`) and `in -> cm` (`* 2.54`).
5. **Observation Provenance Default (`unknown`):**
   - Because neither the ShanghaiT2DM workbooks nor the 1-minute aligned CGMacros CSVs include a vendor native-reading indicator column, 100% of real-archive readings (`98,791` in Shanghai v1, `115,548` in Shanghai v3, and `418,165` in CGMacros T2D) are ingested with `observation_provenance="unknown"`.
