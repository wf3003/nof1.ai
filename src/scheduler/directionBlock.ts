/**
 * 方向阻断机制 — 从 SmartTrade2 移植
 *
 * 当同一币种+方向连败 N 次后，自动屏蔽该方向 M 个周期。
 * 防止 AI 在亏损方向上反复开仓（如 LINK 做多连续4次、AAVE做空连续2次）。
 *
 * 核心逻辑：
 *   1. 每笔交易平仓时，记录 symbol+side 的盈亏
 *   2. 若同方向累计连败 >= 3 次 → 屏蔽 12 个决策周期
 *   3. 屏蔽期间 AI 的该方向信号自动跳过
 *   4. 屏蔽结束后连败计数清零
 */

import { createLogger } from "../utils/loggerUtils";

const logger = createLogger({ name: "direction-block", level: "info" });

/** 方向连败跟踪：key = "symbol:side" (如 "BTC:long") */
export const directionLoss = new Map<string, { count: number; blockUntilCycle: number }>();

/** 屏蔽周期数 */
export const DIRECTION_BLOCK_CYCLES = 12;

/** 连败触发阈值 */
export const MAX_CONSECUTIVE_LOSSES = 3;

/** 当前决策周期号（由 tradingLoop 更新） */
export let currentCycle = 0;
export function setCurrentCycle(n: number) { currentCycle = n; }

/**
 * 平仓时记录结果，判断是否触发方向阻断
 * @returns true 表示已触发阻断
 */
export function recordTradeClose(
  symbol: string,
  side: "long" | "short",
  pnl: number,
): { blocked: boolean; reason?: string } {
  const key = `${symbol}:${side}`;
  const entry = directionLoss.get(key);

  if (pnl >= 0) {
    // 盈利 → 重置连败计数
    if (entry && entry.count > 0) {
      logger.info(`✅ ${key} 盈利 $${pnl.toFixed(2)}，重置连败计数`);
    }
    directionLoss.set(key, { count: 0, blockUntilCycle: 0 });
    return { blocked: false };
  }

  // 亏损 → 累加连败
  const newCount = (entry?.count || 0) + 1;
  if (newCount >= MAX_CONSECUTIVE_LOSSES) {
    const blockUntil = currentCycle + DIRECTION_BLOCK_CYCLES;
    directionLoss.set(key, { count: newCount, blockUntilCycle: blockUntil });
    logger.warn(
      `🚫 ${key} 连败${newCount}次 → 屏蔽到周期#${blockUntil} ` +
      `(剩余${DIRECTION_BLOCK_CYCLES}周期)`,
    );
    return { blocked: true, reason: `连败${newCount}次` };
  }

  directionLoss.set(key, { count: newCount, blockUntilCycle: entry?.blockUntilCycle || 0 });
  logger.info(`⚠️ ${key} 连败${newCount}次 (阈值${MAX_CONSECUTIVE_LOSSES})`);
  return { blocked: false };
}

/**
 * 检查某个方向是否被阻断
 * @returns true 表示当前不可交易该方向
 */
export function isDirectionBlocked(
  symbol: string,
  side: "long" | "short",
): { blocked: boolean; reason?: string; remainingCycles?: number } {
  const key = `${symbol}:${side}`;
  const entry = directionLoss.get(key);
  if (!entry || entry.blockUntilCycle <= 0) return { blocked: false };

  if (currentCycle < entry.blockUntilCycle) {
    const remaining = entry.blockUntilCycle - currentCycle;
    return {
      blocked: true,
      reason: `连败${entry.count}次`,
      remainingCycles: remaining,
    };
  }

  // 屏蔽结束 → 清除
  directionLoss.delete(key);
  return { blocked: false };
}

/**
 * 手动重置某个方向的阻断（如AI复盘建议解除）
 */
export function resetDirectionBlock(symbol: string, side: "long" | "short") {
  const key = `${symbol}:${side}`;
  directionLoss.delete(key);
  logger.info(`🔓 手动解除 ${key} 方向阻断`);
}

/**
 * 获取所有阻断状态（供前端展示）
 */
export function getBlockedDirections(): Array<{
  symbol: string;
  side: string;
  count: number;
  remainingCycles: number;
}> {
  const result: Array<{
    symbol: string;
    side: string;
    count: number;
    remainingCycles: number;
  }> = [];

  for (const [key, entry] of directionLoss) {
    if (entry.blockUntilCycle > currentCycle) {
      const [symbol, side] = key.split(":");
      result.push({
        symbol,
        side,
        count: entry.count,
        remainingCycles: entry.blockUntilCycle - currentCycle,
      });
    }
  }
  return result;
}
