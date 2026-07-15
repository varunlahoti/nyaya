// Mirrors the backend API contract (docs/API_SPEC.md).

export interface Statute {
  act: string;
  sections: string[];
}

export interface ParsedFacts {
  summary: string;
  legal_issues: string[];
  causes_of_action: string[];
  statutes: Statute[];
  keywords: string[];
  area_of_law: string;
  jurisdiction_hint: string;
  court_level_hint: string;
}

export interface JudgmentResult {
  rank: number;
  judgment_id: string;
  title: string;
  citation?: string | null;
  court?: string | null;
  court_level?: string | null;
  date?: string | null;
  source: string;
  url?: string | null;
  relevance_score: number;
  relevance_note: string;
  holding: string;
}

export interface SearchResponse {
  search_id: string;
  cached: boolean;
  latency_ms: number;
  parsed: ParsedFacts;
  results: JudgmentResult[];
  sources_used: string[];
  partial: boolean;
  notice?: string | null;
  disclaimer: string;
}

export interface SearchRequest {
  facts: string;
  jurisdiction: string;
  court_level: string;
  max_results: number;
  deep?: boolean;
}
