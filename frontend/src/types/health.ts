export interface HealthResponse {
  status: "ok";
  service: string;
  version: string;
  environment: string;
  timestamp: string;
}

export interface DatabaseHealthResponse {
  status: "ok" | "unavailable";
  database:
    | "connected"
    | "database_not_configured"
    | "unsupported_database_version"
    | "database_unavailable";
  min_required_major_version: number;
  detected_major_version: number | null;
  timestamp: string;
}
