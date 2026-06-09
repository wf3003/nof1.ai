/**
 * DeepSeek API 兼容的 fetch 中间件
 *
 * 1. 注入 thinking: disabled 以禁用思考模式
 * 2. 将 role: "developer" 转换为 role: "system"（@ai-sdk/openai 可能生成 developer 角色）
 * 3. 删除 temperature（推理模型不支持）
 */
export function createDeepSeekFetch(): (
  input: RequestInfo | URL,
  init?: RequestInit
) => Promise<Response> {
  return async (input, init) => {
    const options = init as any;
    const url = input as string | URL;
    if (options?.body) {
      try {
        const body = JSON.parse(options.body as string);

        // 1. 禁用思考模式
        body.thinking = { type: "disabled" };

        // 2. 删除 temperature（DeepSeek 推理模型不支持）
        delete body.temperature;

        // 3. 将 developer 角色转为 system（DeepSeek API 不支持 developer）
        if (body.messages && Array.isArray(body.messages)) {
          for (const msg of body.messages) {
            if (msg.role === "developer") {
              msg.role = "system";
            }
          }
        }

        options.body = JSON.stringify(body);
      } catch {}
    }
    return fetch(url, options as any);
  };
}
