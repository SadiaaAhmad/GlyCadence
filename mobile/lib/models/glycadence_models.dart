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
      diabetesType: json['diabetes_type'] as String? ?? 'T2D',
      sourceDataset: json['source_dataset'] as String? ?? '',
    );
  }
}

class GlucoseReadingPoint {
  final String recordedAt;
  final double glucoseMgDl;

  const GlucoseReadingPoint({required this.recordedAt, required this.glucoseMgDl});

  factory GlucoseReadingPoint.fromJson(Map<String, dynamic> json) {
    return GlucoseReadingPoint(
      recordedAt: json['recorded_at'] as String? ?? '',
      glucoseMgDl: (json['glucose_mg_dl'] as num?)?.toDouble() ?? 0.0,
    );
  }
}

class GlucoseReadingsData {
  final double targetLow;
  final double targetHigh;
  final double? latestMgDl;
  final String trendArrow;
  final String sourceSummary;
  final List<GlucoseReadingPoint> readings;

  const GlucoseReadingsData({
    required this.targetLow,
    required this.targetHigh,
    required this.latestMgDl,
    required this.trendArrow,
    required this.sourceSummary,
    required this.readings,
  });

  factory GlucoseReadingsData.fromJson(Map<String, dynamic> json) {
    return GlucoseReadingsData(
      targetLow: (json['target_low_mg_dl'] as num?)?.toDouble() ?? 70.0,
      targetHigh: (json['target_high_mg_dl'] as num?)?.toDouble() ?? 180.0,
      latestMgDl: (json['latest_glucose_mg_dl'] as num?)?.toDouble(),
      trendArrow: json['trend_arrow'] as String? ?? 'steady',
      sourceSummary: json['source_summary'] as String? ?? '',
      readings: (json['readings'] as List<dynamic>? ?? [])
          .whereType<Map<String, dynamic>>()
          .map(GlucoseReadingPoint.fromJson)
          .toList(),
    );
  }
}

class GlucoseSummary {
  final double? meanGlucoseMgDl;
  final double? tirPct;
  final double? tbrPct;
  final double? tarPct;

  const GlucoseSummary({
    required this.meanGlucoseMgDl,
    required this.tirPct,
    required this.tbrPct,
    required this.tarPct,
  });

  factory GlucoseSummary.fromJson(Map<String, dynamic> json) {
    return GlucoseSummary(
      meanGlucoseMgDl: (json['mean_glucose_mg_dl'] as num?)?.toDouble(),
      tirPct: (json['tir_pct'] as num?)?.toDouble(),
      tbrPct: (json['tbr_pct'] as num?)?.toDouble(),
      tarPct: (json['tar_pct'] as num?)?.toDouble(),
    );
  }
}

class RecipeNutrition {
  final double carbsG;
  final double sugarG;
  final double fibreG;
  final double proteinG;
  final double fatG;
  final double kcal;
  final double estimatedGl;
  final String glBand;

  const RecipeNutrition({
    required this.carbsG,
    required this.sugarG,
    required this.fibreG,
    required this.proteinG,
    required this.fatG,
    required this.kcal,
    required this.estimatedGl,
    required this.glBand,
  });

  factory RecipeNutrition.fromJson(Map<String, dynamic> json) {
    return RecipeNutrition(
      carbsG: (json['carbs_g'] as num?)?.toDouble() ?? 0.0,
      sugarG: (json['sugar_g'] as num?)?.toDouble() ?? 0.0,
      fibreG: (json['fibre_g'] as num?)?.toDouble() ?? 0.0,
      proteinG: (json['protein_g'] as num?)?.toDouble() ?? 0.0,
      fatG: (json['fat_g'] as num?)?.toDouble() ?? 0.0,
      kcal: (json['kcal'] as num?)?.toDouble() ?? 0.0,
      estimatedGl: (json['estimated_gl'] as num?)?.toDouble() ?? 0.0,
      glBand: json['gl_band'] as String? ?? 'Low',
    );
  }
}

class RecipeItem {
  final String id;
  final String name;
  final String slot;
  final String costTier;
  final int prepMin;
  final String imageUrl;
  final String guidanceNote;
  final List<String> steps;
  final List<Map<String, dynamic>> ingredients;
  final RecipeNutrition nutrition;

  const RecipeItem({
    required this.id,
    required this.name,
    required this.slot,
    required this.costTier,
    required this.prepMin,
    required this.imageUrl,
    required this.guidanceNote,
    required this.steps,
    required this.ingredients,
    required this.nutrition,
  });

  factory RecipeItem.fromJson(Map<String, dynamic> json) {
    return RecipeItem(
      id: json['id'] as String? ?? '',
      name: json['name'] as String? ?? '',
      slot: json['slot'] as String? ?? '',
      costTier: json['cost_tier'] as String? ?? 'low',
      prepMin: (json['prep_min'] as num?)?.toInt() ?? 20,
      imageUrl: json['image_url'] as String? ?? '',
      guidanceNote: json['guidance_note'] as String? ?? '',
      steps: (json['steps'] as List<dynamic>? ?? []).map((e) => e.toString()).toList(),
      ingredients: (json['ingredients'] as List<dynamic>? ?? [])
          .whereType<Map<String, dynamic>>()
          .toList(),
      nutrition: RecipeNutrition.fromJson(json['nutrition'] as Map<String, dynamic>? ?? {}),
    );
  }
}

class MealDetailData {
  final RecipeItem recipe;
  final String recommendedTimeWindow;
  final String bestTimeReason;
  final int timesObserved;
  final String personalSummary;
  final List<Map<String, dynamic>> curvePoints;
  final List<String> whatItMayMean;

  const MealDetailData({
    required this.recipe,
    required this.recommendedTimeWindow,
    required this.bestTimeReason,
    required this.timesObserved,
    required this.personalSummary,
    required this.curvePoints,
    required this.whatItMayMean,
  });

  factory MealDetailData.fromJson(Map<String, dynamic> json) {
    final ph = json['personal_history'] as Map<String, dynamic>? ?? {};
    return MealDetailData(
      recipe: RecipeItem.fromJson(json['recipe'] as Map<String, dynamic>? ?? {}),
      recommendedTimeWindow: json['recommended_time_window'] as String? ?? '',
      bestTimeReason: json['best_time_reason'] as String? ?? '',
      timesObserved: (ph['times_observed'] as num?)?.toInt() ?? 0,
      personalSummary: ph['summary_text'] as String? ?? '',
      curvePoints: (ph['curve_points'] as List<dynamic>? ?? [])
          .whereType<Map<String, dynamic>>()
          .toList(),
      whatItMayMean: (json['what_it_may_mean'] as List<dynamic>? ?? [])
          .map((e) => e.toString())
          .toList(),
    );
  }
}

class ChatSessionItem {
  final String id;
  final String title;
  final String? preview;

  const ChatSessionItem({required this.id, required this.title, this.preview});

  factory ChatSessionItem.fromJson(Map<String, dynamic> json) {
    return ChatSessionItem(
      id: json['id'] as String? ?? '',
      title: json['title'] as String? ?? 'Conversation',
      preview: json['last_message_preview'] as String?,
    );
  }
}

class ChatMessageItem {
  final String id;
  final String role;
  final String content;
  final List<Map<String, dynamic>> cards;
  final bool? safetyPassed;

  const ChatMessageItem({
    required this.id,
    required this.role,
    required this.content,
    required this.cards,
    this.safetyPassed,
  });

  factory ChatMessageItem.fromJson(Map<String, dynamic> json) {
    return ChatMessageItem(
      id: json['id'] as String? ?? '',
      role: json['role'] as String? ?? 'cadie',
      content: json['content'] as String? ?? '',
      cards: (json['cards'] as List<dynamic>? ?? [])
          .whereType<Map<String, dynamic>>()
          .toList(),
      safetyPassed: json['safety_passed'] as bool?,
    );
  }
}

class TodayOverviewData {
  final String displayName;
  final String greetingLine;
  final double? latestMgDl;
  final String trend;
  final double? tirPct;
  final List<Map<String, dynamic>> nextUp;
  final Map<String, dynamic>? featuredRecipe;

  const TodayOverviewData({
    required this.displayName,
    required this.greetingLine,
    required this.latestMgDl,
    required this.trend,
    required this.tirPct,
    required this.nextUp,
    required this.featuredRecipe,
  });

  factory TodayOverviewData.fromJson(Map<String, dynamic> json) {
    final hero = json['hero'] as Map<String, dynamic>? ?? {};
    return TodayOverviewData(
      displayName: json['display_name'] as String? ?? 'Patient',
      greetingLine: json['greeting_line'] as String? ?? '',
      latestMgDl: (hero['latest_mg_dl'] as num?)?.toDouble(),
      trend: hero['trend'] as String? ?? 'steady',
      tirPct: (hero['tir_pct'] as num?)?.toDouble(),
      nextUp: (json['next_up'] as List<dynamic>? ?? [])
          .whereType<Map<String, dynamic>>()
          .toList(),
      featuredRecipe: json['featured_recipe'] as Map<String, dynamic>?,
    );
  }
}
