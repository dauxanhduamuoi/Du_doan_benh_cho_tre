import type {
  PublishedMedicalKnowledgeSelector,
  WeatherAIPredictResponse,
} from '@/lib/api';


const TIER1_TO_MEDICAL_FACTOR: Readonly<Record<string, string>> = {
  temperature: 'temperature',
  humidity: 'humidity',
  precipitation: 'precipitation',
  wind: 'wind',
  weather_code: 'weather_condition',
};


export function buildPublishedMedicalKnowledgeSelectors(
  response: WeatherAIPredictResponse,
): PublishedMedicalKnowledgeSelector[] {
  const selectors: PublishedMedicalKnowledgeSelector[] = [];
  const seen = new Set<string>();
  for (const prediction of response.predictions ?? response.top_risks ?? []) {
    for (const factor of prediction.tier1?.positive_factors ?? []) {
      if (factor.direction !== 'UP' || factor.shap_value <= 0) continue;
      let selector: PublishedMedicalKnowledgeSelector | null = null;
      if (factor.category === 'WEATHER') {
        const weatherFactor = TIER1_TO_MEDICAL_FACTOR[String(factor.weather_factor ?? '')];
        if (weatherFactor) selector = {
          disease_group_id: prediction.disease_group_id,
          factor_type: 'WEATHER',
          factor_key: weatherFactor,
          factor_value: null,
          weather_factor: weatherFactor as PublishedMedicalKnowledgeSelector['weather_factor'],
        };
      } else if (factor.category === 'DEMOGRAPHIC' && factor.feature === 'age_group') {
        const value = typeof factor.input_value === 'string' ? factor.input_value.trim() : '';
        if (value) selector = {
          disease_group_id: prediction.disease_group_id,
          factor_type: 'AGE',
          factor_key: 'age_group',
          factor_value: value,
          weather_factor: null,
        };
      } else if (factor.category === 'DEMOGRAPHIC' && factor.feature === 'gender') {
        const value = typeof factor.input_value === 'string' ? factor.input_value.trim() : '';
        if (value) selector = {
          disease_group_id: prediction.disease_group_id,
          factor_type: 'SEX',
          factor_key: 'gender',
          factor_value: value,
          weather_factor: null,
        };
      } else if (factor.category === 'SEASONAL_CALENDAR') {
        selector = {
          disease_group_id: prediction.disease_group_id,
          factor_type: 'SEASONALITY',
          factor_key: 'time_of_year',
          factor_value: null,
          weather_factor: null,
        };
      }
      if (!selector) continue;
      const key = `${selector.disease_group_id}\u0000${selector.factor_type}\u0000${selector.factor_key}\u0000${selector.factor_value ?? ''}`;
      if (seen.has(key)) continue;
      seen.add(key);
      selectors.push(selector);
    }
  }
  return selectors;
}
