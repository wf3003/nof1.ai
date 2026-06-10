/**
 * 级联过滤器 — 从 SmartTrade2 移植
 *
 * 在 AI 决策之后、实际开仓之前，增加多层独立过滤：
 *   1. AI 评分 (score ≥ 阈值)
 *   2. 行情质量 (marketQuality ≥ 阈值)
 *   3. 入场质量 (entryQuality ≥ 阈值)
 *   4. 方向阻断检查
 *   5. 仓位上限检查
 *
 * 每层输出日志，可追踪拦截原因。
 *
 * 与 SmartTrade2 的级联过滤逻辑一致，
 * 但适配 nof1.ai 的数据结构。
 */

import { createLogger } from "../utils/loggerUtils";
import { isDirectionBlocked } from "./directionBlock";
import { RISK_PARAMS } from "../config/riskParams";

const logger = createLogger({ name: "cascade-filter", level: "info" });

/** 可热加载的拦截参数（AI 复盘可调） */
export const interceptParams = new Map<string, number>([
  ["aiScoreMin", 40],           // AI 最低评分
  ["marketQualityMin", 30],     // 行情质量最低阈值
  ["entryQualityMin", 35],      // 入场质量最低阈值
  ["maxPositions", RISK_PARAMS.MAX_POSITIONS],
  ["rsiExtremeShort", 20],      // RSI 低于此值禁止做空
  ["rsiExtremeLong", 80],       // RSI 高于此值禁止做多
  ["minLeverageAfterLoss", 2],  // 亏损后最低杠杆
  ["maxChaseSameSymbol", 2],    // 同一币种最多追仓次数
]);

export interface CascadeInput {
  symbol: string;
  side: "long" | "short";
  aiScore: number;          // AI 决策评分 (0-100)
  marketQuality: number;    // 行情质量 (0-100)
  entryQuality: number;     // 入场质量 (0-100)
  rsi1h: number;            // 1h RSI
  leverage: number;         // 建议杠杆
  amountPercent: number;    // 建议仓位%
  existingPositions: number;// 当前持仓数
  sameSymbolPositions: number; // 同币种已有持仓数
  lastTradeLost: boolean;   // 上一笔是否亏损
}

export interface CascadeResult {
  passed: boolean;
  adjustedLeverage?: number;
  adjustedAmount?: number;
  blockReasons: string[];
}

/**
 * 运行级联过滤
 */
export function runCascadeFilter(input: CascadeInput): CascadeResult {
  const reasons: string[] = [];
  let leverage = input.leverage;
  let amount = input.amountPercent;

  // ---- 第0层：方向阻断（从 SmartTrade2 移植） ----
  const dirBlock = isDirectionBlocked(input.symbol, input.side);
  if (dirBlock.blocked) {
    reasons.push(`[阻断]${input.symbol} ${input.side} 方向阻断中,剩余${dirBlock.remainingCycles}周期(${dirBlock.reason})`);
    return { passed: false, blockReasons: reasons };
  }

  // ---- 第1层：AI 评分 ----
  const aiScoreMin = interceptParams.get("aiScoreMin") || 40;
  if (input.aiScore < aiScoreMin) {
    reasons.push(`[AI]评分${input.aiScore}<${aiScoreMin}，拦截`);
    return { passed: false, blockReasons: reasons };
  }
  if (input.aiScore < 50) {
    amount = Math.round(amount * 0.5);
    reasons.push(`[AI]评分${input.aiScore}<50，仓位减半至${amount}%`);
  }

  // ---- 第2层：行情质量 ----
  const mqMin = interceptParams.get("marketQualityMin") || 30;
  if (input.marketQuality < mqMin) {
    reasons.push(`[MQ]行情质量${input.marketQuality}<${mqMin}，拦截`);
    return { passed: false, blockReasons: reasons };
  }
  if (input.marketQuality < 50) {
    amount = Math.round(amount * 0.6);
    reasons.push(`[MQ]行情质量${input.marketQuality}<50，仓位×0.6→${amount}%`);
  }

  // ---- 第3层：入场质量 ----
  const eqMin = interceptParams.get("entryQualityMin") || 35;
  if (input.entryQuality < eqMin) {
    reasons.push(`[EQ]入场质量${input.entryQuality}<${eqMin}，拦截`);
    return { passed: false, blockReasons: reasons };
  }
  if (input.entryQuality < 55) {
    amount = Math.round(amount * 0.7);
    reasons.push(`[EQ]入场质量${input.entryQuality}<55，仓位×0.7→${amount}%`);
  }

  // ---- 第4层：RSI 极端位保护 ----
  const rsiShort = interceptParams.get("rsiExtremeShort") || 20;
  const rsiLong = interceptParams.get("rsiExtremeLong") || 80;
  if (input.side === "short" && input.rsi1h < rsiShort) {
    reasons.push(`[RSI]${input.symbol} RSI${input.rsi1h}<${rsiShort}，做空危险，拦截`);
    return { passed: false, blockReasons: reasons };
  }
  if (input.side === "long" && input.rsi1h > rsiLong) {
    reasons.push(`[RSI]${input.symbol} RSI${input.rsi1h}>${rsiLong}，做多危险，拦截`);
    return { passed: false, blockReasons: reasons };
  }

  // ---- 第5层：仓位上限 ----
  const maxPos = interceptParams.get("maxPositions") || RISK_PARAMS.MAX_POSITIONS;
  if (input.existingPositions >= maxPos) {
    reasons.push(`[仓位]已有${input.existingPositions}个持仓≥上限${maxPos}，拦截`);
    return { passed: false, blockReasons: reasons };
  }

  // ---- 第6层：追仓限制 ----
  const maxChase = interceptParams.get("maxChaseSameSymbol") || 2;
  if (input.sameSymbolPositions >= maxChase) {
    reasons.push(`[追仓]${input.symbol}已有${input.sameSymbolPositions}次追仓≥上限${maxChase}，拦截`);
    return { passed: false, blockReasons: reasons };
  }

  // ---- 第7层：亏损后降杠杆 ----
  if (input.lastTradeLost) {
    const minLev = interceptParams.get("minLeverageAfterLoss") || 2;
    if (leverage > minLev * 2) {
      leverage = Math.max(minLev, Math.floor(leverage * 0.7));
      reasons.push(`[杠杆]上一笔亏损，杠杆降至${leverage}x`);
    }
  }

  // ---- 第8层：最小值保护 ----
  const minAmount = Math.max(2, Math.round((RISK_PARAMS.MAX_LEVERAGE > 0 ? 100 / RISK_PARAMS.MAX_LEVERAGE : 5)));
  if (amount < minAmount) {
    amount = minAmount;
    reasons.push(`[保护]仓位触及最小值，恢复至${amount}%`);
  }

  return {
    passed: true,
    adjustedLeverage: leverage,
    adjustedAmount: amount,
    blockReasons: reasons,
  };
}

/**
 * 获取拦截参数值（供前端展示）
 */
export function getInterceptParam(name: string, fallback: number): number {
  return interceptParams.get(name) ?? fallback;
}

/**
 * 更新拦截参数（AI 复盘后调用）
 */
export function setInterceptParam(name: string, value: number) {
  interceptParams.set(name, value);
  logger.info(`⚙️ 拦截参数调整: ${name}=${value}`);
}
