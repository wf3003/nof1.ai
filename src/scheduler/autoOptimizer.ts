/**
 * 自动调参优化器 — 从 SmartTrade2 移植
 *
 * 定期分析 indicator_snapshots 和已平仓交易的历史数据，
 * 统计每个指标在不同区间下的胜率，生成可执行的 opt_rules 规则。
 *
 * 流程：
 *   1. 查询所有已平仓的 snapshots
 *   2. 对每个数值指标，按值排序 → 均匀分段 → 算每段胜率
 *   3. 如果某段与全局基线偏差 > 15%，且样本数 >= 5，则生成规则
 *   4. 规则存到 opt_rules 表，供 cascadeFilter 消费
 *
 * 适配 nof1.ai 的 LibSQL 数据库（@libsql/client）。
 */

import { createLogger } from "../utils/loggerUtils";
import { createClient } from "@libsql/client";
import { getChinaTimeISO } from "../utils/timeUtils";
import { setInterceptParam } from "./cascadeFilter";

const logger = createLogger({ name: "auto-optimizer", level: "info" });

const dbClient = createClient({
  url: process.env.DATABASE_URL || "file:./.voltagent/trading.db",
});

interface Segment {
  label: string;
  min: number;
  max: number;
  wins: number;
  losses: number;
}

const INDICATORS = [
  { field: "rsi_1h", name: "rsi_1h" },
  { field: "rsi_1d", name: "rsi_1d" },
  { field: "adx_1h", name: "adx_1h" },
  { field: "adx_1d", name: "adx_1d" },
  { field: "atr_pct", name: "atr_pct" },
  { field: "market_quality", name: "market_quality" },
  { field: "entry_quality", name: "entry_quality" },
];

/**
 * 获取已平仓的快照数据
 */
async function getClosedSnapshots(limit: number): Promise<any[]> {
  try {
    const result = await dbClient.execute({
      sql: `SELECT * FROM indicator_snapshots WHERE result IN ('win', 'loss') ORDER BY id DESC LIMIT ?`,
      args: [limit],
    });
    return (result.rows || []).map((row: any) => ({
      result: row.result,
      side: row.side,
      rsi_1h: row.rsi_1h,
      rsi_1d: row.rsi_1d,
      adx_1h: row.adx_1h,
      adx_1d: row.adx_1d,
      atr_pct: row.atr_pct,
      market_quality: row.market_quality,
      entry_quality: row.entry_quality,
    }));
  } catch {
    return [];
  }
}

/**
 * 计算全局基线胜率
 */
function computeBaseline(snapshots: any[]): { total: number; wins: number; winRate: number } {
  const wins = snapshots.filter((s: any) => s.result === "win").length;
  const total = snapshots.length;
  return { total, wins, winRate: total > 0 ? wins / total : 0 };
}

/**
 * 按值分段统计胜率（均分5段）
 */
function segmentByDeciles(snapshots: any[], field: string): Segment[] {
  const valid = snapshots
    .filter((s: any) => s[field] != null && !isNaN(s[field]))
    .sort((a: any, b: any) => a[field] - b[field]);

  if (valid.length < 10) return [];

  const n = valid.length;
  const segSize = Math.ceil(n / 5);
  const segments: Segment[] = [];

  for (let i = 0; i < n; i += segSize) {
    const chunk = valid.slice(i, i + segSize);
    if (chunk.length < 3) continue;
    const wins = chunk.filter((s: any) => s.result === "win").length;
    segments.push({
      label: `seg${Math.floor(i / segSize) + 1}`,
      min: chunk[0][field],
      max: chunk[chunk.length - 1][field],
      wins,
      losses: chunk.length - wins,
    });
  }
  return segments;
}

/**
 * 主入口：运行一轮优化分析
 * @returns 新生成的规则数量
 */
export async function runOptimizer(): Promise<number> {
  const snapshots = await getClosedSnapshots(500);
  if (snapshots.length < 25) {
    logger.info(`[Optimizer] 样本不足(${snapshots.length})，跳过`);
    return 0;
  }

  const baseline = computeBaseline(snapshots);
  logger.info(
    `[Optimizer] 基线: 样本=${baseline.total} 胜率=${(baseline.winRate * 100).toFixed(0)}%`,
  );

  let rulesCreated = 0;

  for (const ind of INDICATORS) {
    const segs = segmentByDeciles(snapshots, ind.field);
    for (const seg of segs) {
      const segTotal = seg.wins + seg.losses;
      if (segTotal < 5) continue;
      const segWr = segTotal > 0 ? seg.wins / segTotal : 0;
      const diff = segWr - baseline.winRate;
      if (Math.abs(diff) < 0.15) continue;

      let impactType: string;
      let impactValue: number;
      if (diff > 0) {
        // 高胜率段 → 奖励乘数
        impactType = "multiply";
        impactValue = segWr > baseline.winRate * 1.5 ? 1.3 : 1.1;
      } else {
        // 低胜率段 → 惩罚乘数
        impactType = "multiply";
        impactValue = segWr < baseline.winRate * 0.5 ? 0.4 : 0.6;
      }

      try {
        // 检查是否已有相似规则
        const existing = await dbClient.execute({
          sql: `SELECT id FROM opt_rules WHERE indicator=? AND operator=? AND val1=? AND val2=? AND active=1`,
          args: [ind.field, "between", seg.min, seg.max],
        });

        if ((existing.rows || []).length > 0) {
          // 更新已有规则
          await dbClient.execute({
            sql: `UPDATE opt_rules SET impact_type=?, impact_value=?, created_at=? WHERE id=?`,
            args: [impactType, impactValue, getChinaTimeISO(), (existing.rows![0] as any).id],
          });
        } else {
          // 插入新规则
          await dbClient.execute({
            sql: `INSERT INTO opt_rules (target, indicator, operator, val1, val2, impact_type, impact_value, active, created_at)
                  VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)`,
            args: [
              "score",
              ind.field,
              "between",
              seg.min,
              seg.max,
              impactType,
              impactValue,
              getChinaTimeISO(),
            ],
          });
          rulesCreated++;
        }

        logger.info(
          `[Optimizer] ${ind.field} [${seg.min.toFixed(2)},${seg.max.toFixed(2)}] ` +
          `胜率=${(segWr * 100).toFixed(0)}% (基线${(baseline.winRate * 100).toFixed(0)}%) ` +
          `→ ${impactType} ${impactValue} (${rulesCreated}条新规则)`,
        );
      } catch (e: any) {
        logger.error(`[Optimizer] 规则写入失败: ${e.message}`);
      }
    }
  }

  // 同时建议调整拦截参数
  if (snapshots.length >= 50 && baseline.winRate < 0.35) {
    const newAiMin = Math.min(60, Math.round(40 + (0.35 - baseline.winRate) * 100));
    setInterceptParam("aiScoreMin", newAiMin);
    logger.warn(`[Optimizer] 全局胜率偏低(${(baseline.winRate * 100).toFixed(0)}%)，aiScoreMin→${newAiMin}`);
  }

  return rulesCreated;
}

/**
 * 加载活跃规则（供 cascadeFilter 使用）
 */
export async function loadOptRules(): Promise<any[]> {
  try {
    const result = await dbClient.execute({
      sql: `SELECT * FROM opt_rules WHERE active = 1 ORDER BY created_at DESC`,
      args: [],
    });
    return (result.rows || []).map((row: any) => ({
      ...row,
      val1: Number(row.val1),
      val2: row.val2 != null ? Number(row.val2) : null,
      impact_value: Number(row.impact_value),
    }));
  } catch {
    return [];
  }
}

/**
 * 插入指标快照（开仓时调用）
 */
export async function insertIndicatorSnapshot(data: {
  decision_id?: number;
  symbol: string;
  side: string;
  rsi_1h?: number;
  rsi_1d?: number;
  adx_1h?: number;
  adx_1d?: number;
  atr_pct?: number;
  funding_rate?: number;
  volume_24h?: number;
  market_quality?: number;
  entry_quality?: number;
  leverage: number;
  position_pct: number;
  ai_score: number;
  signal_type?: string;
}): Promise<void> {
  try {
    await dbClient.execute({
      sql: `INSERT INTO indicator_snapshots 
            (decision_id, time, symbol, side, rsi_1h, rsi_1d, adx_1h, adx_1d, atr_pct, funding_rate, volume_24h, market_quality, entry_quality, leverage, position_pct, ai_score, signal_type, result)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')`,
      args: [
        data.decision_id || null,
        getChinaTimeISO(),
        data.symbol,
        data.side,
        data.rsi_1h || null,
        data.rsi_1d || null,
        data.adx_1h || null,
        data.adx_1d || null,
        data.atr_pct || null,
        data.funding_rate || null,
        data.volume_24h || null,
        data.market_quality || null,
        data.entry_quality || null,
        data.leverage,
        data.position_pct,
        data.ai_score,
        data.signal_type || "ai_signal",
      ],
    });
  } catch (e: any) {
    logger.warn(`[Snapshot] 快照写入失败 ${data.symbol}: ${e.message}`);
  }
}

/**
 * 平仓时更新快照结果
 */
export async function updateSnapshotResult(symbol: string, pnl: number, closeType: string): Promise<void> {
  try {
    const result = pnl >= 0 ? "win" : "loss";
    await dbClient.execute({
      sql: `UPDATE indicator_snapshots SET result=?, pnl=?, close_type=? 
            WHERE symbol=? AND result='open' ORDER BY id DESC LIMIT 1`,
      args: [result, pnl, closeType, symbol],
    });
  } catch {
    // 静默失败
  }
}
