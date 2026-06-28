import apiClient from './index';

export interface ReverseTrainingStatus {
  historyCount: number;
  successCount: number;
  failCount: number;
  successRate: number;
  dateRange: { start: string; end: string };
  uniqueStocks: number;
  accuracyLog: AccuracyRecord[];
  collectedCount: number;
}

export interface AccuracyRecord {
  date: string;
  matchRate: number;
  matchCount: number;
  totalCount: number;
  recordedAt: string;
}

export interface HistoryPickItem {
  id: number;
  pickDate: string;
  stockCode: string;
  stockName: string;
  pickPrice: number | null;
  prevClose: number | null;
  pickDayChange: number | null;
  nextDayChange: number | null;
  success: number;
}

export interface HistoryDateGroup {
  date: string;
  picks: HistoryPickItem[];
  successCount: number;
  failCount: number;
  total: number;
}

export interface HistoryResponse {
  total: number;
  page: number;
  pageSize: number;
  dates: HistoryDateGroup[];
  items: HistoryPickItem[];
  allDates: string[];
}

export interface ScanResult {
  enabled: boolean;
  candidates: ScanCandidate[];
  candidateCount: number;
  snapshotCount: number;
  afterFilterCount: number;
  elapsedSeconds: number;
}

export interface ScanCandidate {
  code: string;
  name: string;
  price: number;
  changePct: number;
  score: number;
  trendStatus: string;
  trendStrength: number;
  biasMa5: number;
  volumeStatus: string;
  macdStatus: string;
  buySignal: string;
  reason: string;
}

export interface CompareResult {
  date: string;
  thirdParty: string[];
  thirdPartyDetail: CompareThirdPartyDetail[];
  thirdPartyFail: string[];
  strategyPicks: string[];
  matches: string[];
  matchCount: number;
  matchRate: number;
  onlyThird: CompareOnlyItem[];
  onlyStrategy: CompareOnlyItem[];
}

export interface CompareThirdPartyDetail {
  code: string;
  name: string;
  pickPrice: number | null;
  prevClose: number | null;
  pickDayChange: number | null;
  nextDayChange: number | null;
  success: number | null;
}

export interface CompareOnlyItem {
  code: string;
  isFail?: boolean;
  name?: string;
  pickPrice?: number | null;
  nextDayChange?: number | null;
  strategyDetail?: ScanCandidate;
}

export interface AddPicksResponse {
  added: number;
  total: number;
  successRate: number;
}

export interface PickItem {
  stockCode: string;
  stockName?: string;
  pickPrice?: number | null;
  prevClose?: number | null;
  pickDayChange?: number | null;
  nextDayChange?: number | null;
  success?: number;
}

export const reverseTrainingApi = {
  getStatus: async (): Promise<ReverseTrainingStatus> => {
    const res = await apiClient.get('/api/v1/reverse-training/status');
    return toCamelCase<ReverseTrainingStatus>(res.data);
  },

  getHistory: async (params: Record<string, unknown> = {}): Promise<HistoryResponse> => {
    const res = await apiClient.get('/api/v1/reverse-training/history', { params });
    return toCamelCase<HistoryResponse>(res.data);
  },

  addPicks: async (data: {
    date: string;
    picks: PickItem[];
    successFlags?: Record<string, number>;
  }): Promise<AddPicksResponse> => {
    const payload: Record<string, unknown> = {
      date: data.date,
      picks: data.picks.map(p => toSnakeCase(p)),
    };
    if (data.successFlags) payload.success_flags = data.successFlags;
    const res = await apiClient.post('/api/v1/reverse-training/picks', payload);
    return toCamelCase<AddPicksResponse>(res.data);
  },

  updatePick: async (id: number, data: Record<string, unknown>): Promise<{ success: boolean; record: HistoryPickItem }> => {
    const res = await apiClient.put(`/api/v1/reverse-training/picks/${id}`, data);
    return toCamelCase(res.data);
  },

  deletePick: async (id: number): Promise<{ success: boolean }> => {
    const res = await apiClient.delete(`/api/v1/reverse-training/picks/${id}`);
    return toCamelCase(res.data);
  },

  deletePicksByDate: async (date: string): Promise<{ success: boolean; deleted: number }> => {
    const res = await apiClient.delete('/api/v1/reverse-training/picks', { params: { date } });
    return toCamelCase(res.data);
  },

  migrateFromCsv: async (): Promise<{ migrated: number; insertedOrUpdated: number }> => {
    const res = await apiClient.post('/api/v1/reverse-training/migrate-from-csv');
    return toCamelCase(res.data);
  },

  runScan: async (topN: number = 5): Promise<ScanResult> => {
    const res = await apiClient.post('/api/v1/reverse-training/scan', { top_n: topN });
    return toCamelCase<ScanResult>(res.data);
  },

  runCompare: async (date?: string): Promise<CompareResult> => {
    const res = await apiClient.post('/api/v1/reverse-training/compare', { date: date || '' });
    return toCamelCase<CompareResult>(res.data);
  },

  getLatestCompare: async (): Promise<CompareResult> => {
    const res = await apiClient.get('/api/v1/reverse-training/compare/latest');
    return toCamelCase<CompareResult>(res.data);
  },

  runTrain: async (): Promise<{ taskId: string; status: string; message: string }> => {
    const res = await apiClient.post('/api/v1/reverse-training/train');
    return toCamelCase(res.data);
  },

  getTrainingStatus: async (taskId: string): Promise<TaskStatus> => {
    const res = await apiClient.get(`/api/v1/reverse-training/train/status/${taskId}`);
    return toCamelCase<TaskStatus>(res.data);
  },

  getAccuracy: async (): Promise<AccuracyRecord[]> => {
    const res = await apiClient.get('/api/v1/reverse-training/accuracy');
    return toCamelCase<AccuracyRecord[]>(res.data);
  },
};

export interface TaskStatus {
  taskId: string;
  status: string;
  progress: number;
  message: string;
}

function toCamelCase<T>(obj: unknown): T {
  if (obj === null || obj === undefined) return obj as T;
  if (Array.isArray(obj)) return obj.map((item) => toCamelCase(item)) as T;
  if (typeof obj === 'object') {
    const result: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(obj)) {
      const camelKey = key.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
      result[camelKey] = toCamelCase(value);
    }
    return result as T;
  }
  return obj as T;
}

function toSnakeCase(obj: unknown): unknown {
  if (obj === null || obj === undefined) return obj;
  if (Array.isArray(obj)) return obj.map((item) => toSnakeCase(item));
  if (typeof obj === 'object') {
    const result: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(obj)) {
      const snakeKey = key.replace(/[A-Z]/g, (c) => '_' + c.toLowerCase());
      result[snakeKey] = toSnakeCase(value);
    }
    return result;
  }
  return obj;
}
