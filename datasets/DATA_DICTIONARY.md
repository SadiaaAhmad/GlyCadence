# GlyCadence Research Datasets — Data Dictionary, Access & Provenance

> [!IMPORTANT]
> Raw research participant datasets must remain in `datasets/raw/` (git-ignored) and must **never** be committed to version control.
> All research records ingested into PostgreSQL are tagged with `cohort_type = 'research_participant'` and linked to an immutable `dataset_imports` row storing the exact SHA-256 source-file checksum, dataset version, and preprocessing pipeline version.

---

## 1. ShanghaiT2DM (`shanghai_t2dm`)

### Official Access, Citation & License
- **Title:** *Chinese diabetes datasets for data-driven machine learning* (Zhao et al., *Scientific Data* 10, 35, 2023)
- **Repository / DOI:** Figshare Collection (`https://doi.org/10.6084/m9.figshare.c.6310860` / Dataset DOI `10.6084/m9.figshare.21582507`)
- **Access Model:** Open Access
- **License:** Creative Commons Attribution 4.0 International (**CC BY 4.0**)
- **Retention Policy in GlyCadence:** `dataset_license_bound` / `research_archive` (protected against arbitrary deletion by database trigger `trg_patients_retention_before_delete`).

### Cohort & Sampling Conventions
- **Participants:** 100 Type 2 Diabetes Mellitus (`diabetes_type = 'T2D'`) patients in Shanghai, China (`Shanghai_T2DM/` directory + `Shanghai_T2DM_Summary.xlsx`).
- **Monitoring Window:** 3 to 14 consecutive days per monitoring period (some patients have multiple periods, e.g., `2000_0_...`, `2000_1_...`).
- **Primary CGM Sensor:** Abbott **FreeStyle Libre H** (`device_id = 'FreeStyle_Libre_H'`).
- **Native CGM Sampling Interval:** **15 minutes** (`sampling_interval_min = 15`).

### Column Specifications & Units

#### A. Summary Sheet (`Shanghai_T2DM_Summary.xlsx` / `.csv`)
| Source Column | Unit / Type | GlyCadence Mapping | Notes |
| :--- | :--- | :--- | :--- |
| `Patient Number` | String (e.g. `2000_0_20201230`) | `patients.external_id`, `clinical_records.source_record_id` | Prefix before `_` identifies unique patient; full ID identifies monitoring file |
| `Gender` | `Female` / `Male` (or `F`/`M`/`1`/`2`) | `patients.sex` | Normalized to `female` / `male` / `unknown` |
| `Age (years)` | Integer (years) | `patients.age` | Validated `1 <= age <= 120` |
| `Height (m)` or `Height (cm)` | Float (`m` or `cm`) | `patients.height_cm` | Converted to `cm` if reported in meters (`< 3.0`) |
| `Weight (kg)` | Float (`kg`) | `patients.weight_kg` | Stored in `kg` |
| `BMI (kg/m2)` | Float (`kg/m^2`) | `clinical_records.bmi` | Stored in `clinical_records` |
| `Fasting Plasma Glucose (mg/dl)` | Float (`mg/dL` or `mmol/L`) | `clinical_records.fasting_glucose_mg_dl` | Converted if `mmol/L` (`* 18.0182`) |
| `HbA1c (%)` or `HbA1c (mmol/mol)` | Float (`%`) | `clinical_records.hba1c_pct` | Stored on `clinical_records` |
| `Hypoglycemic Agents` / `Insulin` | Text | `medications` | Stored as prescribed regimens only (**never** fabricated as timestamped `taken`/`missed` events) |

#### B. Participant Time-Series Files (`Shanghai_T2DM/*.xlsx`, `*.xls`, `*.csv`)
| Source Column | Raw Unit | GlyCadence Table & Field | Handling & Non-Negotiable Rules |
| :--- | :--- | :--- | :--- |
| `Date` | Timestamp (`YYYY-MM-DD HH:MM:SS`) | `recorded_at` / `logged_at` / `event_time` | Normalized to timezone-aware UTC (`Asia/Shanghai` `+08:00` if naive source timestamp) |
| `CGM (mg / dl)` | `mg/dL` (or `mmol/L` if header specifies) | `glucose_readings` (`reading_type='cgm'`, `device_id='FreeStyle_Libre_H'`, `sampling_interval_min=15`) | Preserves `raw_value` and `raw_unit`; rejects `<= 0` or `>= 1500 mg/dL` or duplicate `(patient_id, recorded_at, reading_type)` |
| `CBG (mg / dl)` | `mg/dL` | `glucose_readings` (`reading_type='cbg'`, `sampling_interval_min=NULL`) | Capillary fingerstick spot reading |
| `Dietary intake` | Text / grams description | `meals.description` | Logged when non-empty and not `"data not available"`; macros remain `NULL` if unquantified |
| `Non-insulin hypoglycemic agents` | Text | `medications` + `medication_events` (`status='unknown'`, `event_source='clinical_record'`) | Recorded as clinical record notation; **never** inferred as `taken` or `missed` unless explicitly stated |
| `Insulin dose - s.c.` / `Insulin dose - i.v.` | Text | `medications` + `medication_events` (`status='unknown'`, `event_source='clinical_record'`) | Preserves exact dose text in `notes` |

---

## 2. CGMacros (`cgmacros`)

### Official Access, Citation & License
- **Title:** *CGMacros: a scientific dataset for personalized nutrition and diet monitoring* (Gutierrez-Osuna et al., PhysioNet v1.0.0)
- **Repository / DOI:** PhysioNet (`https://doi.org/10.13026/3zdc-eb88`)
- **Access Model:** Open Access on PhysioNet
- **License:** Creative Commons Attribution 4.0 International (**CC BY 4.0**)
- **Retention Policy in GlyCadence:** `dataset_license_bound` / `research_archive`

### Cohort & Strict T2D Separation Rules
- **Total Participants:** 45 adults tracked for ~10 days (`CGMacros-001` through `CGMacros-049`).
- **Metabolic Classification (from `bio.csv` `A1c PDL (Lab)`):**
  - **Healthy (`diabetes_type = 'healthy'`):** 15 participants (`HbA1c < 5.7%`)
  - **Prediabetes (`diabetes_type = 'prediabetes'`):** 16 participants (`5.7% <= HbA1c <= 6.4%`)
  - **Type 2 Diabetes (`diabetes_type = 'T2D'`):** **14 participants** (`HbA1c > 6.4%`)
- **Non-Negotiable Cohort Rule:**
  - Only the **14 T2D participants** (`diabetes_type = 'T2D'`) may be included in T2D-specific clinical/nutrition evaluations.
  - Non-T2D participants (`prediabetes`, `healthy`) are either filtered out when `t2d_only=True` (default for T2D evaluation) or explicitly tagged with their true `diabetes_type` (`prediabetes` / `healthy`) so they are **never** mixed into T2D validation cohorts.

### Dual-CGM Native Sampling Preservation
- Participants wore two blinded CGM sensors simultaneously:
  1. **Abbott FreeStyle Libre Pro (`Libre GL`):** Native sampling interval = **15 minutes** (`device_id = 'FreeStyle_Libre_Pro'`, `sampling_interval_min = 15`).
  2. **Dexcom G6 Pro (`Dexcom GL`):** Native sampling interval = **5 minutes** (`device_id = 'Dexcom_G6_Pro'`, `sampling_interval_min = 5`).
- **Crucial Ingestion Rule for 1-Minute Aligned CSVs:**
  - The main CGMacros participant CSV files align rows on a 1-minute grid and linearly interpolate between native sensor readings.
  - To obey *"Preserve native sampling intervals and timestamps"* and *"Never silently interpolate large CGM gaps"*, the GlyCadence CGMacros ingestion pipeline supports:
    - Down-sampling / filtering 1-minute interpolated grids back to native cadence (`15 min` for `Libre GL`, `5 min` for `Dexcom GL`) when `preserve_native_cadence=True` (default), or recording the exact native `sampling_interval_min` (`15` for Libre, `5` for Dexcom) alongside `device_id`.

### Column Specifications & Units (`bio.csv` & `CGMacros-XXX.csv`)

#### A. `bio.csv` (Baseline Demographics & Labs)
| Source Column | Unit | GlyCadence Field |
| :--- | :--- | :--- |
| `subject` | Integer / ID (`1`–`49`) | `patients.external_id` (`CGMacros-001`, etc.) |
| `Age` | Years | `patients.age` |
| `Gender` | `M` / `F` | `patients.sex` |
| `Body weight` | `lbs` or `kg` (per `DataDictionary_Bio.csv`) | `patients.weight_kg` |
| `Height` | `inches` or `cm` | `patients.height_cm` |
| `BMI` | `kg/m^2` | `clinical_records.bmi` |
| `A1c PDL (Lab)` | `%` | `clinical_records.hba1c_pct` + classifies `diabetes_type` (`> 6.4` => `T2D`, `5.7–6.4` => `prediabetes`, `< 5.7` => `healthy`) |
| `Fasting GLU - PDL (Lab)` | `mg/dL` | `clinical_records.fasting_glucose_mg_dl` |

#### B. Participant Time-Series CSV (`CGMacros-XXX.csv`)
| Source Column | Unit | GlyCadence Table & Field |
| :--- | :--- | :--- |
| `Timestamp` | `YYYY-MM-DD HH:MM:SS` or `M/D/YYYY H:MM` | Normalized to UTC `TIMESTAMPTZ` |
| `Libre GL` | `mg/dL` | `glucose_readings` (`device_id='FreeStyle_Libre_Pro'`, `sampling_interval_min=15`, `reading_type='cgm'`) |
| `Dexcom GL` | `mg/dL` | `glucose_readings` (`device_id='Dexcom_G6_Pro'`, `sampling_interval_min=5`, `reading_type='cgm'`) |
| `Meal Type` | `Breakfast`, `Lunch`, `Dinner`, `Snack`, `Snacks` | `meals.meal_type` (normalized lowercase) |
| `Calories`, `Carbs`, `Protein`, `Fat`, `Fiber` | `kcal`, `g` | `meals.calories`, `carbs_g`, `protein_g`, `fat_g`, `fiber_g` |
| `HR`, `Steps` / `METs` | `bpm`, `steps` | `activity_records` (when non-null) |
