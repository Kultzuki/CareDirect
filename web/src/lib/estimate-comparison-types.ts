export interface ComparisonSource {
  path: string;
  source: { document_id: string; page: number; snippet: string | null; bbox?: unknown } | null;
  state: string;
  needs_review?: boolean;
}
export interface ComparisonLine {
  line_number: number | null;
  description: string | null;
  quantity: string | null;
  unit_price: string | null;
  line_total: string | null;
  sources: ComparisonSource[];
}
export interface EstimateComparison {
  status: string;
  extraction_providers?: Record<string, string>;
  summary: string;
  currency?: string;
  difference?: string | null;
  itemized_difference?: string | null;
  estimate_total?: string | null;
  final_total?: string | null;
  estimate_document_id?: string;
  final_document_id?: string;
  warnings?: string[];
  limitations?: string[];
  total_sources?: { estimate: ComparisonSource[]; final: ComparisonSource[] };
  documents: { id: string; document_type: string; extraction_status: string; created_at: string }[];
  rows: {
    description: string;
    code: string | null;
    estimate: string | null;
    final: string | null;
    difference: string | null;
    changes: string[];
    estimate_lines: ComparisonLine[];
    final_lines: ComparisonLine[];
  }[];
}
