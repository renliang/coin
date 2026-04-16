import { get } from "./client";

export interface SentimentSignalData {
  symbol: string;
  score: number;
  direction: string;
  confidence: number;
  created_at: string;
}

export interface SentimentItemData {
  id: number;
  source: string;
  symbol: string;
  score: number;
  confidence: number;
  raw_text: string;
  timestamp: string;
}

export interface SentimentHistoryPoint {
  date: string;
  score: number;
  direction: string;
}

export function fetchSentimentLatest() {
  return get<{ signals: SentimentSignalData[] }>("/sentiment/latest");
}

export function fetchSentimentHistory(symbol = "", days = 7) {
  return get<{ history: SentimentHistoryPoint[] }>("/sentiment/history", {
    symbol,
    days: String(days),
  });
}

export function fetchSentimentItems(params: {
  source?: string;
  symbol?: string;
  page?: string;
  per_page?: string;
}) {
  return get<{
    items: SentimentItemData[];
    total: number;
    page: number;
    per_page: number;
  }>("/sentiment/items", params);
}
