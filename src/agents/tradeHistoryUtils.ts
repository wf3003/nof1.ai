export interface TradeHistoryEntry {
  id?: number;
  symbol: string;
  side: "long" | "short" | string;
  type: "open" | "close" | string;
  price: number;
  quantity: number;
  leverage: number;
  pnl: number | null;
  fee: number;
  timestamp: string;
  status: string;
}

export interface ClosedTradeSummary {
  profitCount: number;
  lossCount: number;
  totalCount: number;
  longCount: number;
  shortCount: number;
  totalProfit: number;
  winRate: number;
  longRate: number;
}

export function getRecentTrades(
  trades: TradeHistoryEntry[] | undefined,
  limit: number = 10,
): TradeHistoryEntry[] {
  if (!trades || trades.length === 0) {
    return [];
  }

  return trades.slice(-limit);
}

export function getRecentClosedTrades(
  trades: TradeHistoryEntry[] | undefined,
  limit: number = 10,
): TradeHistoryEntry[] {
  if (!trades || trades.length === 0) {
    return [];
  }

  return trades.filter((trade) => trade.type === "close").slice(-limit);
}

export function summarizeClosedTrades(
  trades: TradeHistoryEntry[] | undefined,
): ClosedTradeSummary {
  const summary: ClosedTradeSummary = {
    profitCount: 0,
    lossCount: 0,
    totalCount: 0,
    longCount: 0,
    shortCount: 0,
    totalProfit: 0,
    winRate: 0,
    longRate: 0,
  };

  if (!trades || trades.length === 0) {
    return summary;
  }

  for (const trade of trades) {
    const pnl = trade.pnl ?? 0;

    if (trade.side === "long") {
      summary.longCount++;
    } else if (trade.side === "short") {
      summary.shortCount++;
    }

    if (pnl > 0) {
      summary.profitCount++;
    } else if (pnl < 0) {
      summary.lossCount++;
    }

    summary.totalProfit += pnl;
  }

  summary.totalCount = summary.profitCount + summary.lossCount;
  summary.winRate =
    summary.totalCount > 0
      ? (summary.profitCount / summary.totalCount) * 100
      : 0;

  const directionalCount = summary.longCount + summary.shortCount;
  summary.longRate =
    directionalCount > 0 ? (summary.longCount / directionalCount) * 100 : 0;

  return summary;
}

export function getMostRecentCloseTrade(
  trades: TradeHistoryEntry[] | undefined,
): TradeHistoryEntry | undefined {
  if (!trades || trades.length === 0) {
    return undefined;
  }

  for (let i = trades.length - 1; i >= 0; i--) {
    if (trades[i]?.type === "close") {
      return trades[i];
    }
  }

  return undefined;
}
