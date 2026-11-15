class PatientSummary {
  final String id;
  final String cohortType;
  final String? externalId;
  final String displayName;
  final String diabetesType;
  final String sourceDataset;

  const PatientSummary({
    required this.id,
    required this.cohortType,
    required this.externalId,
    required this.displayName,
    required this.diabetesType,
    required this.sourceDataset,
  });

  factory PatientSummary.fromJson(Map<String, dynamic> json) {
    return PatientSummary(
      id: json['id'] as String,
      cohortType: json['cohort_type'] as String? ?? 'synthetic_demo',
      externalId: json['external_id'] as String?,
      displayName: json['display_name'] as String? ?? 'Patient',
      diabetesType: json['diabetes_type'] as String? ?? 'T2DM',
      sourceDataset: json['source_dataset'] as String? ?? '',
    );
  }

  bool get isResearchDataset => cohortType == 'research_participant';
}

class GlucoseSummary {
  final String patientId;
  final String cohortType;
  final double? meanGlucoseMgDl;
  final double? cvPct;
  final double? tirPct;
  final double? tbrPct;
  final double? tarPct;
  final int nativeObservationCount;
  final int datasetDocumentedObservationCount;
  final int archiveAlignedObservationCount;
  final double periodCoveragePct;
  final Map<String, int> provenanceCounts;

  const GlucoseSummary({
    required this.patientId,
    required this.cohortType,
    required this.meanGlucoseMgDl,
    required this.cvPct,
    required this.tirPct,
    required this.tbrPct,
    required this.tarPct,
    required this.nativeObservationCount,
    required this.datasetDocumentedObservationCount,
    required this.archiveAlignedObservationCount,
    required this.periodCoveragePct,
    required this.provenanceCounts,
  });

  factory GlucoseSummary.fromJson(Map<String, dynamic> json) {
    final coverage = json['coverage'] as Map<String, dynamic>? ?? {};
    final rawCounts = coverage['provenance_counts'] as Map<String, dynamic>? ?? {};
    final counts = <String, int>{};
    rawCounts.forEach((k, v) {
      if (v is num) counts[k] = v.toInt();
    });
    return GlucoseSummary(
      patientId: json['patient_id'] as String? ?? '',
      cohortType: json['cohort_type'] as String? ?? '',
      meanGlucoseMgDl: (json['mean_glucose_mg_dl'] as num?)?.toDouble(),
      cvPct: (json['cv_pct'] as num?)?.toDouble(),
      tirPct: (json['tir_pct'] as num?)?.toDouble(),
      tbrPct: (json['tbr_pct'] as num?)?.toDouble(),
      tarPct: (json['tar_pct'] as num?)?.toDouble(),
      nativeObservationCount: (json['native_observation_count'] as num?)?.toInt() ?? 0,
      datasetDocumentedObservationCount:
          (json['dataset_documented_observation_count'] as num?)?.toInt() ?? 0,
      archiveAlignedObservationCount:
          (json['archive_aligned_observation_count'] as num?)?.toInt() ?? 0,
      periodCoveragePct: (coverage['period_coverage_pct'] as num?)?.toDouble() ?? 0.0,
      provenanceCounts: counts,
    );
  }
}

class MealResponseItem {
  final String mealId;
  final String loggedAt;
  final String mealType;
  final String description;
  final double? baselineGlucoseMgDl;
  final double? peakGlucoseMgDl;
  final double? iaucMgDlMin;
  final String validity;

  const MealResponseItem({
    required this.mealId,
    required this.loggedAt,
    required this.mealType,
    required this.description,
    required this.baselineGlucoseMgDl,
    required this.peakGlucoseMgDl,
    required this.iaucMgDlMin,
    required this.validity,
  });

  factory MealResponseItem.fromJson(Map<String, dynamic> json) {
    return MealResponseItem(
      mealId: json['meal_id'] as String? ?? '',
      loggedAt: json['logged_at'] as String? ?? '',
      mealType: json['meal_type'] as String? ?? 'meal',
      description: json['description'] as String? ?? '',
      baselineGlucoseMgDl: (json['baseline_glucose_mg_dl'] as num?)?.toDouble(),
      peakGlucoseMgDl: (json['peak_glucose_mg_dl'] as num?)?.toDouble(),
      iaucMgDlMin: (json['iauc_mg_dl_min'] as num?)?.toDouble(),
      validity: json['validity'] as String? ?? 'insufficient_data',
    );
  }
}

class AgentTraceStep {
  final String node;
  final String startedAt;
  final String endedAt;
  final String status;
  final String summary;
  final int evidenceCount;

  const AgentTraceStep({
    required this.node,
    required this.startedAt,
    required this.endedAt,
    required this.status,
    required this.summary,
    required this.evidenceCount,
  });

  factory AgentTraceStep.fromJson(Map<String, dynamic> json) {
    return AgentTraceStep(
      node: json['node'] as String? ?? '',
      startedAt: json['started_at'] as String? ?? '',
      endedAt: json['ended_at'] as String? ?? '',
      status: json['status'] as String? ?? 'completed',
      summary: json['summary'] as String? ?? '',
      evidenceCount: (json['evidence_count'] as num?)?.toInt() ?? 0,
    );
  }
}

class VerifierReport {
  final bool passed;
  final String verificationStatus;
  final List<String> failedReasons;
  final List<String> details;
  final List<String> checkedProvenances;

  const VerifierReport({
    required this.passed,
    required this.verificationStatus,
    required this.failedReasons,
    required this.details,
    required this.checkedProvenances,
  });

  factory VerifierReport.fromJson(Map<String, dynamic> json) {
    return VerifierReport(
      passed: json['passed'] as bool? ?? false,
      verificationStatus: json['verification_status'] as String? ?? 'rejected',
      failedReasons: (json['failed_reasons'] as List<dynamic>? ?? [])
          .map((e) => e.toString())
          .toList(),
      details:
          (json['details'] as List<dynamic>? ?? []).map((e) => e.toString()).toList(),
      checkedProvenances: (json['checked_provenances'] as List<dynamic>? ?? [])
          .map((e) => e.toString())
          .toList(),
    );
  }
}

class InvestigationRun {
  final String id;
  final String patientId;
  final String datasetLabel;
  final bool isResearchDataset;
  final String executionMode;
  final String modelUsed;
  final String? fallbackReason;
  final String? primarySummaryPatient;
  final String? primarySummaryClinician;
  final bool safetyPassed;
  final bool isSafeToDisplay;
  final List<String> clinicianQuestions;
  final List<String> crossSignalFindings;
  final List<AgentTraceStep> trace;
  final VerifierReport verifierReport;
  final String createdAt;

  const InvestigationRun({
    required this.id,
    required this.patientId,
    required this.datasetLabel,
    required this.isResearchDataset,
    required this.executionMode,
    required this.modelUsed,
    required this.fallbackReason,
    required this.primarySummaryPatient,
    required this.primarySummaryClinician,
    required this.safetyPassed,
    required this.isSafeToDisplay,
    required this.clinicianQuestions,
    required this.crossSignalFindings,
    required this.trace,
    required this.verifierReport,
    required this.createdAt,
  });

  factory InvestigationRun.fromJson(Map<String, dynamic> json) {
    final doc = json['doctor_report'] as Map<String, dynamic>?;
    return InvestigationRun(
      id: json['id'] as String? ?? '',
      patientId: json['patient_id'] as String? ?? '',
      datasetLabel: json['dataset_label'] as String? ?? '',
      isResearchDataset: json['is_research_dataset'] as bool? ?? false,
      executionMode: json['execution_mode'] as String? ?? 'deterministic_fallback',
      modelUsed: json['model_used'] as String? ?? 'unknown',
      fallbackReason: json['fallback_reason'] as String?,
      primarySummaryPatient: json['primary_summary_patient'] as String?,
      primarySummaryClinician: json['primary_summary_clinician'] as String?,
      safetyPassed: json['safety_passed'] as bool? ?? false,
      isSafeToDisplay: (doc?['is_safe_to_display'] as bool?) ?? false,
      clinicianQuestions: (doc?['clinician_questions'] as List<dynamic>? ?? [])
          .map((e) => e.toString())
          .toList(),
      crossSignalFindings: (json['cross_signal_findings'] as List<dynamic>? ?? [])
          .map((e) => e.toString())
          .toList(),
      trace: (json['trace'] as List<dynamic>? ?? [])
          .whereType<Map<String, dynamic>>()
          .map(AgentTraceStep.fromJson)
          .toList(),
      verifierReport: VerifierReport.fromJson(
        json['verifier_report'] as Map<String, dynamic>? ?? {},
      ),
      createdAt: json['created_at'] as String? ?? '',
    );
  }
}
