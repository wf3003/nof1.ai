/**
 * open-nof1.ai - Alpha Enhanced 策略
 * 融合 crypto-trader Python 项目的最佳交易理念
 * 
 * 2026-05-22 数据驱动优化（基于 22 笔实盘回测）：
 *   - 14x高杠杆 + 25%胜率 + 0.18盈亏比 = 亏损
 *   - 手续费 = 亏损的 52%（高频交易代价）
 *   - 优化重点：降杠杆、提胜率、压手续费
 */

import type { StrategyParams, StrategyPromptContext } from "./types";

export function getAlphaEnhancedStrategy(maxLeverage: number): StrategyParams {
  const aeLevMin = Math.max(2, Math.ceil(maxLeverage * 0.48));
  const aeLevMax = Math.max(3, maxLeverage);
  const aeLevGood = Math.ceil((aeLevMin + aeLevMax) * 0.6);

  return {
    name: "Alpha Enhanced",
    description: "源自 crypto-trader alpha-beta：12-25x杠杆+紧止损+快止盈+AI完全风控",

    leverageMin: aeLevMin,
    leverageMax: aeLevMax,
    leverageRecommend: {
      normal: `${aeLevMin}倍`,
      good: `${aeLevGood}倍`,
      strong: `${aeLevMax}倍`,
    },

    positionSizeMin: 8,
    positionSizeMax: 35,
    positionSizeRecommend: {
      normal: "8-12%",
      good: "12-18%",
      strong: "25-35%",
    },
    maxTotalMarginPercent: 40,

    stopLoss: { low: -3, mid: -3, high: -3 },

    trailingStop: {
      level1: { trigger: 3, stopAt: 1 },
      level2: { trigger: 6, stopAt: 3 },
      level3: { trigger: 10, stopAt: 6 },
    },

    partialTakeProfit: {
      stage1: { trigger: 3, closePercent: 50 },
      stage2: { trigger: 7, closePercent: 70 },
      stage3: { trigger: 15, closePercent: 100 },
    },

    peakDrawdownProtection: 25,

    volatilityAdjustment: {
      highVolatility: { leverageFactor: 0.70, positionFactor: 0.80 },
      normalVolatility: { leverageFactor: 1.0, positionFactor: 1.0 },
      lowVolatility: { leverageFactor: 1.10, positionFactor: 1.0 },
    },

    entryCondition: "信号置信度≥0.55，技术面+消息面综合判断",
    riskTolerance: "统一-3%止损，低频精选交易",
    tradingStyle: "AI完全自主决策，技术面+消息面综合判断，只选最强信号",

    enableCodeLevelProtection: true,
    allowAiOverrideProtection: true,
  };
}

export function generateAlphaEnhancedPrompt(
  params: StrategyParams,
  context: StrategyPromptContext
): string {
  return `## Alpha Enhanced 信号策略（系统执行模式）

你是一个信号生成器。你只能输出以下格式的 JSON，不允许输出任何其他文字。

### 📊 必须分析以下数据
1. 技术指标（EMA、MACD、RSI、ATR）
2. 资金费率和未平仓量
3. 消息面（快讯、公告）
4. 当前持仓和盈亏
5. 最近交易历史

### 📤 输出格式（纯 JSON）

仅对 TOP1 最佳信号币种输出决策。如果没有合适机会输出 hold。

做多:
{"action":"buy","symbol":"BTC","leverage":3,"amountPercent":18,"reason":"EMA多头排列+MACD金叉","confidence":0.65}

做空:
{"action":"sell","symbol":"ETH","leverage":3,"amountPercent":15,"reason":"跌破EMA20+RSI下穿50","confidence":0.60}

观望:
{"action":"hold","symbol":"","leverage":0,"amountPercent":0,"reason":"所有币种信号不明确","confidence":0.0}

### 📐 参数范围
- leverage: ${params.leverageMin}-${params.leverageMax}
- amountPercent: ${params.positionSizeMin}-${params.positionSizeMax}
- confidence: 0.0-1.0（低于0.55系统不会执行）
- reason: 不超过30字

### 🎯 交易理念
1. **做多和做空平等**：每个周期同时评估多空
2. **只选最佳**：只对信号最强的1个币种
3. **拒绝模糊**：没把握就 hold
4. **手续费意识**：同一币种1小时内不开第二次
5. **趋势为王**：逆势信号降低杠杆和confidence`;
}
