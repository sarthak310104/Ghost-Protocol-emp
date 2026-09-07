/**
 * Every request goes through `credentials: "include"` so the browser
 * sends the httpOnly ghost_session cookie automatically. This file
 * never reads, stores, or touches the raw API key or session token in
 * JS-accessible state (localStorage, a JS variable, React state) --
 * that's the entire point of an httpOnly cookie: if this code can't
 * read the token, neither can an XSS payload injected into the page.
 */
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      message = body.detail ?? message;
    } catch {
      // response wasn't JSON -- fall back to statusText, already set above
    }
    throw new ApiError(res.status, typeof message === "string" ? message : JSON.stringify(message));
  }

  // 204/empty-body responses (e.g. some future DELETE) won't have JSON to parse
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export interface Workspace {
  workspace_id: string;
  name: string;
}

export interface Incident {
  id: string;
  title: string;
  status: "open" | "diagnosing" | "resolved" | "dismissed";
  severity: "low" | "medium" | "high" | "critical";
  primary_service: string;
  started_at: string;
  last_seen_at: string;
  resolved_at: string | null;
}

export interface Bottleneck {
  service: string;
  fan_in: number;
  fan_out: number;
  critical_path_membership: number;
  error_rate_baseline: number;
  risk_score: number;
  contributing_edges: string[];
  // Per-service risk baseline -- "unusual FOR THIS SERVICE," not a
  // fixed cutoff applied uniformly. reference_risk_score/risk_zscore
  // are null until enough scan history exists for that service.
  reference_risk_score: number | null;
  has_reference_baseline: boolean;
  risk_zscore: number | null;
}

export interface GraphEdge {
  caller: string;
  callee: string;
  current_latency_ms_p50: number;
  current_latency_ms_p99: number;
  current_error_rate: number;
  reference_latency_ms: number;
  reference_error_rate: number;
  has_reference_baseline: boolean;
  sample_count: number;
}

export interface Observation {
  metric: string;
  current: number;
  baseline?: number;
}

export interface TimelineEntry {
  kind: string;
  message: string;
  occurred_at: string;
}

export interface DeploymentMarker {
  service_name: string;
  version: string;
  deployed_at: string;
  minutes_before_incident: number;
}

export interface Deployment {
  id: string;
  service_name: string;
  version: string;
  deployed_at: string;
  notes: string | null;
}

export interface MetricProjection {
  edge: string;
  metric: string;
  current: number;
  reference: number;
  ci_low: number;
  ci_high: number;
  note: string;
  // Only present on `projections`, never on `blast_radius` -- the
  // backend only computes this improvement summary for edges directly
  // named in the incident's own evidence.
  projected_improvement?: {
    point_estimate_pct: number;
    ci_95_low_pct: number;
    ci_95_high_pct: number;
  } | null;
}

export interface CohortStat {
  value: string;
  sample_count: number;
  mean_latency_ms: number;
  stddev_latency_ms: number;
}

export interface CohortComparison {
  baseline_cohort: string;
  compared_cohort: string;
  difference_pct: number;
  ci_95_low_pct: number;
  ci_95_high_pct: number;
  method: string;
}

export interface CohortAnalysisResult {
  edge: string;
  dimension: string;
  window_minutes: number;
  cohorts: CohortStat[];
  comparison: CohortComparison | null;
  note: string | null;
}

export interface SimulationResult {
  primary_service: string;
  method: string;
  confidence_level: number;
  projections: MetricProjection[];
  blast_radius: MetricProjection[];
  // Only present when a registered cohort dimension had concurrent
  // data on one of the incident's edges -- see run_incident_simulation.
  cohort_comparisons?: CohortAnalysisResult[];
}

export interface EvidencePackage {
  incident: { id: string; service: string };
  observations: Observation[];
  dependencies: string[];
  timeline: TimelineEntry[];
  deployments: DeploymentMarker[];
  simulation_results: SimulationResult[];
}

export interface DemoPreview {
  configured: boolean;
  services_observed?: number;
  open_incident_count?: number;
  recent_incidents?: { title: string; severity: string; primary_service: string }[];
  top_bottleneck?: { service: string; risk_score: number } | null;
}

export interface CohortDimension {
  id: string;
  attribute_key: string;
  label: string;
}

export interface CohortStat {
  value: string;
  sample_count: number;
  mean_latency_ms: number;
  stddev_latency_ms: number;
}

export interface CohortComparison {
  baseline_cohort: string;
  compared_cohort: string;
  difference_pct: number;
  ci_95_low_pct: number;
  ci_95_high_pct: number;
  method: string;
}

export interface CohortAnalysisResult {
  edge: string;
  dimension: string;
  window_minutes: number;
  cohorts: CohortStat[];
  comparison: CohortComparison | null;
  note: string | null;
}

export interface ServiceSummary {
  name: string;
  first_seen_at: string;
  last_seen_at: string;
  fan_in: number;
  fan_out: number;
  current_risk_score: number;
  has_reference_baseline: boolean;
  risk_zscore: number | null;
}

export interface PipelineEvent {
  kind: string;
  occurred_at: string;
  is_error: boolean;
  detail: string | null;
}

export interface PipelineHealth {
  last_data_received_at: string | null;
  last_scan_at: string | null;
  is_stale: boolean;
  recent_events: PipelineEvent[];
}

export const api = {
  login: (apiKey: string) =>
    request<Workspace>("/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ api_key: apiKey }),
    }),

  demoPreview: () => request<DemoPreview>("/v1/public/demo-preview"),

  cohortDimensions: () => request<CohortDimension[]>("/v1/cohort-dimensions"),

  registerCohortDimension: (attribute_key: string, label: string) =>
    request<CohortDimension>("/v1/cohort-dimensions", {
      method: "POST",
      body: JSON.stringify({ attribute_key, label }),
    }),

  cohortAnalysis: (caller: string, callee: string, dimension: string, window_minutes = 60) =>
    request<CohortAnalysisResult>(
      `/v1/cohort-analysis?caller=${encodeURIComponent(caller)}&callee=${encodeURIComponent(callee)}&dimension=${encodeURIComponent(dimension)}&window_minutes=${window_minutes}`
    ),

  logout: () => request<{ logged_out: boolean }>("/v1/auth/logout", { method: "POST" }),

  me: () => request<Workspace>("/v1/auth/me"),

  incidents: (statusFilter?: string) =>
    request<Incident[]>(statusFilter ? `/v1/incidents?status_filter=${statusFilter}` : "/v1/incidents"),

  incidentEvidence: (id: string) => request<EvidencePackage>(`/v1/incidents/${id}/evidence`),

  resolveIncident: (id: string) =>
    request<{ id: string; status: string }>(`/v1/incidents/${id}/resolve`, { method: "POST" }),

  bottlenecks: () => request<Bottleneck[]>("/v1/bottlenecks"),

  services: () => request<ServiceSummary[]>("/v1/services"),

  pipelineHealth: () => request<PipelineHealth>("/v1/pipeline-health"),

  deployments: (limit?: number) =>
    request<Deployment[]>(limit ? `/v1/deployments?limit=${limit}` : "/v1/deployments"),

  graph: () => request<GraphEdge[]>("/v1/graph"),

  get: <T>(path: string) => request<T>(path),
};