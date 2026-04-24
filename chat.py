import requests
import json
import os
from datetime import datetime
import sys

# ========== 请通过环境变量设置真实密钥 ==========
API_KEY = ""
SERPAPI_KEY = ""
if not API_KEY:
    print("❌ 请设置环境变量 DEEPSEEK_API_KEY")
    sys.exit(1)
# ================================================

# 【优化 3：输出精致化】在系统提示词中增加对排版、缩进和公式的严格约束
SYSTEM_PROMPT = """你是一位专门辅导计算机新生的助教，名叫"小深"。请严格遵守：
1. 永远不要直接给出完整代码，只提供伪代码和思路引导。
2. 学生卡住时，用苏格拉底式提问引导他。
3. 学生完成代码后，帮他检查时间复杂度。
4. 回答要像朋友聊天，避免使用过度生僻的学术词汇。
5. 【排版严控】：如果你需要输出代码，必须保证缩进绝对严格、对齐整齐；如果你需要解释数学公式（如微积分、离散数学等），请尽量用清晰的纯文本或 Markdown 表达，避免输出大量难以在终端阅读的复杂 LaTeX 源码。确保排版美观，步骤完整不遗漏。"""

CHAT_DIR = "chat_history"

PRICING = {
    "deepseek-v4-flash": {"input": 1, "output": 2},   
    "deepseek-v4-pro":   {"input": 12, "output": 24}
}

MAX_CONTEXT_MESSAGES = 20

total_input_tokens = 0
total_output_tokens = 0
current_model = "deepseek-v4-flash"

budget_limit = 0.0        
original_budget = 0.0     
spent_cost = 0.0          

# ---------- 核心能力 1：意图感知与动态适配 ----------
def analyze_intent(user_input, messages):
    """静默分析用户的身份、意图和情绪状态"""
    global total_input_tokens, total_output_tokens, spent_cost
    
    recent_history = [m["content"] for m in messages[-4:] if m["role"] == "user"]
    history_text = "\n".join(recent_history)
    
    prompt = f"""
    请根据用户最近的提问，分析并推测：
    1. 身份推测（如：零基础新生/有一定C基础/来要答案的伸手党等）
    2. 当前意图（如：求导数原理/找代码Bug/理解数据结构等）
    3. 情绪与耐心（如：急躁崩溃/耐心求索等）
    
    历史提问参考：{history_text}
    本次提问：{user_input}
    
    请严格以JSON格式输出，只包含这三个键："identity", "intent", "mood"。不要输出其他任何解释。
    """
    
    try:
        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "deepseek-v4-flash",
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
                "max_tokens": 150
            },
            timeout=10
        )
        result = response.json()
        
        # 计费统计
        usage = result.get("usage", {})
        total_input_tokens += usage.get("prompt_tokens", 0)
        total_output_tokens += usage.get("completion_tokens", 0)
        _, _, cost = calc_cost("deepseek-v4-flash", usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
        spent_cost += cost
        
        content = result["choices"][0]["message"]["content"]
        profile = json.loads(content)
        return profile
    except Exception as e:
        return None

# ---------- 核心能力 2：自我反思与优化 ----------
def reflect_on_answer(last_reply):
    """当交互较短时，让AI自我审查并补充"""
    global total_input_tokens, total_output_tokens, spent_cost
    
    reflection_prompt = f"""
    你刚才给出了以下回答：
    {last_reply}
    
    请反思：
    1. 这个回答是否足够简洁清晰？
    2. 是否有更容易理解的类比？
    3. 逻辑推理或步骤中是否漏掉了关键的转折点或答案？代码缩进是否规范？
    
    如果有明显的改进空间或需要补充关键遗漏，请输出精简的补充版本（以“其实换个角度想...”或“补充一个小细节...”开头）。
    如果已经很好，请严格回复四个字："无需优化"。
    """
    
    try:
        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "deepseek-v4-flash",
                "messages": [{"role": "user", "content": reflection_prompt}],
                "max_tokens": 300
            },
            timeout=15
        )
        result = response.json()
        
        usage = result.get("usage", {})
        total_input_tokens += usage.get("prompt_tokens", 0)
        total_output_tokens += usage.get("completion_tokens", 0)
        _, _, cost = calc_cost("deepseek-v4-flash", usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
        spent_cost += cost
        
        improved = result["choices"][0]["message"]["content"].strip()
        if "无需优化" in improved:
            return None
        return improved
    except Exception:
        return None

# ---------- 联网搜索相关 ----------
def google_search_serpapi(query, num=3):
    if not SERPAPI_KEY:
        print("   ⚠️ 未设置 SERPAPI_KEY，无法联网搜索")
        return []
    url = "https://serpapi.com/search"
    params = {"q": query, "api_key": SERPAPI_KEY, "engine": "google", "num": num}
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        results = [{"title": item.get("title"), "snippet": item.get("snippet"), "link": item.get("link")} for item in data.get("organic_results", [])]
        return results
    except Exception as e:
        print(f"   ⚠️ 搜索出错：{e}")
        return []

def compress_search_results(results, mode="fast"):
    global total_input_tokens, total_output_tokens, spent_cost
    if not results: return "未找到相关网络信息。"
    
    raw_text = "".join([f"{i+1}. 标题：{r['title']}\n   摘要：{r['snippet']}\n" for i, r in enumerate(results)])
    instruction = "把下面搜索结果总结成1-2句话的简短摘要，抓住最重要的那个点：" if mode == "fast" else "把下面搜索结果整理成一小段连贯的摘要，包含核心要点："
    
    try:
        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "deepseek-v4-flash",
                "messages": [
                    {"role": "system", "content": "你是信息压缩助手，只输出精简摘要，不输出任何解释。"},
                    {"role": "user", "content": f"{instruction}\n{raw_text}"}
                ],
                "max_tokens": 300 if mode != "fast" else 100
            }
        )
        result = response.json()
        usage = result.get("usage", {})
        total_input_tokens += usage.get("prompt_tokens", 0)
        total_output_tokens += usage.get("completion_tokens", 0)
        _, _, cost = calc_cost("deepseek-v4-flash", usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
        spent_cost += cost
        return result["choices"][0]["message"]["content"]
    except Exception:
        return f"（压缩失败）{results[0]['title']}：{results[0]['snippet']}"

# ---------- 文件与对话管理 ----------
def ensure_dir():
    if not os.path.exists(CHAT_DIR): os.makedirs(CHAT_DIR)

def list_history_files():
    ensure_dir()
    files = [f for f in os.listdir(CHAT_DIR) if f.endswith('.json')]
    files.sort(reverse=True)
    return files

def save_chat(messages, filename=None):
    ensure_dir()
    if filename is None: filename = f"chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    filepath = os.path.join(CHAT_DIR, filename)
    with open(filepath, 'w', encoding='utf-8') as f: json.dump(messages, f, ensure_ascii=False, indent=2)
    print(f"💾 对话已保存到：{os.path.abspath(filepath)}")
    return filename

def load_chat(filename):
    filepath = os.path.join(CHAT_DIR, filename)
    with open(filepath, 'r', encoding='utf-8') as f: return json.load(f)

def start_menu():
    print("\n" + "=" * 50)
    print("📂 选择对话模式：\n  1. 开始新对话")
    files = list_history_files()
    if files:
        print("  2. 继续之前的对话：")
        for i, f in enumerate(files[:5]): print(f"     [{i+3}] {f}")
    print("=" * 50)
    choice = input("输入序号: ").strip()
    if choice == "1": return None
    elif choice == "2" and files: return files[0]
    elif choice.isdigit() and files:
        idx = int(choice) - 3
        if 0 <= idx < len(files): return files[idx]
    return None

def choose_options():
    global current_model, budget_limit, original_budget
    print("\n" + "=" * 50 + "\n🤖 选择模型：\n  1. V4-Flash (¥1/2)\n  2. V4-Pro   (¥12/24)")
    current_model = "deepseek-v4-flash" if input("输入序号 (1/2): ").strip() == "1" else "deepseek-v4-pro"

    print("\n🌐 开启联网？\n  0. 关\n  1. 极简压缩\n  2. 均衡模式")
    web_choice = input("输入序号 (0/1/2): ").strip()
    
    print("\n💰 设置本次花费限额（元），直接回车不设限额")
    val = input("> ").strip()
    if val:
        try:
            val = float(val)
            budget_limit = val if val > 0 else 0.0
        except: budget_limit = 0.0
    else: budget_limit = 0.0
    original_budget = budget_limit

    print(f"📋 配置完成 | 限额：{'¥'+str(budget_limit) if budget_limit else '不限'}\n" + "=" * 50 + "\n")
    return web_choice, budget_limit

def calc_cost(model, input_tokens, output_tokens):
    price = PRICING.get(model, PRICING["deepseek-v4-flash"])
    i_cost = input_tokens / 1_000_000 * price["input"]
    o_cost = output_tokens / 1_000_000 * price["output"]
    return i_cost, o_cost, i_cost + o_cost

def predict_cost(msgs_for_api, model, max_output_tokens=1024):
    total_chars = sum(len(msg["content"]) for msg in msgs_for_api)
    est_input_tokens = max(1, total_chars // 2)
    _, _, cost = calc_cost(model, est_input_tokens, max_output_tokens)
    return cost

def print_session_stats():
    _, _, total_cost = calc_cost(current_model, total_input_tokens, total_output_tokens)
    print("\n" + "=" * 50 + "\n📊 【本次对话用量统计】\n" + "-" * 50)
    print(f"  Token：入 {total_input_tokens:,} | 出 {total_output_tokens:,} | 总 {total_input_tokens + total_output_tokens:,}")
    print(f"  累计花费：¥{spent_cost:.6f}")
    if budget_limit: print(f"  预算上限：¥{budget_limit:.2f}  (剩余 ¥{max(0, budget_limit - spent_cost):.6f})")
    print("=" * 50 + "\n")

# ---------- 核心对话引擎 ----------
def ask_deepseek(user_input, messages, model, stream=True, search_summary=None):
    global total_input_tokens, total_output_tokens, spent_cost, budget_limit
    
    system_msg = [msg for msg in messages if msg["role"] == "system"]
    non_system = [msg for msg in messages if msg["role"] != "system"]
    
    if len(non_system) > MAX_CONTEXT_MESSAGES:
        non_system = non_system[-MAX_CONTEXT_MESSAGES:]
        if non_system and non_system[0]["role"] == "assistant":
            non_system = non_system[1:]
            
    # 【动态注入意图画像】
    profile = analyze_intent(user_input, non_system)
    dynamic_system = system_msg.copy()
    if profile:
        profile_instruction = f"\n\n【动态画像注入】\n根据分析，当前用户身份可能是：{profile.get('identity', '未知')}。\n他的真实意图是：{profile.get('intent', '未知')}。\n当前情绪状态：{profile.get('mood', '平稳')}。\n请根据以上信息，自适应调整你的语气和代码/理论知识的辅导深度。如果用户急躁，直接给核心思路；如果用户愿意深究，多用引导式提问。"
        dynamic_system[0]["content"] += profile_instruction

    msgs_for_api = dynamic_system + non_system
    
    api_user_content = f"（网络信息摘要：{search_summary}）\n基于此回答：{user_input}" if search_summary else user_input
    api_messages = msgs_for_api + [{"role": "user", "content": api_user_content}]
    
    if budget_limit > 0:
        est_cost = predict_cost(api_messages, model)
        remaining = budget_limit - spent_cost
        if est_cost > remaining:
            print(f"\n⚠️ 预算预警：预估 ¥{est_cost:.6f}，剩余 ¥{remaining:.6f}")
            if input("继续并增加原有额度？(y/n): ").strip().lower() == 'y':
                budget_limit += original_budget
            else:
                return None

    try:
        payload = {"model": model, "messages": api_messages, "stream": stream}
        if stream: payload["stream_options"] = {"include_usage": True}

        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json=payload, stream=stream, timeout=60
        )
        response.raise_for_status()

        full_reply = ""
        if stream:
            print("小深：", end="", flush=True)
            for line in response.iter_lines():
                if line:
                    decoded = line.decode('utf-8')
                    if decoded.startswith("data: "):
                        data_str = decoded[6:]
                        if data_str.strip() == "[DONE]": break
                        try:
                            chunk = json.loads(data_str)
                            if "choices" in chunk and len(chunk["choices"]) > 0:
                                content = chunk["choices"][0].get("delta", {}).get("content", "")
                                if content:
                                    print(content, end="", flush=True)
                                    full_reply += content
                            
                            if "usage" in chunk and chunk["usage"] is not None:
                                usage = chunk["usage"]
                                total_input_tokens += usage.get("prompt_tokens", 0)
                                total_output_tokens += usage.get("completion_tokens", 0)
                                _, _, cost = calc_cost(model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
                                spent_cost += cost
                        except json.JSONDecodeError: pass
            print() 
        else:
            # 兼容非流式
            pass

        # 【智能静默反思环节】
        # 如果最近对话较少，说明是一个新的短交互，可以触发反思机制
        if len(non_system) <= 4:
            improved_reply = reflect_on_answer(full_reply)
            if improved_reply:
                print(f"\n✨ 小深反思后补充：\n{improved_reply}\n")
                full_reply += f"\n\n（补充信息：{improved_reply}）"

        messages.append({"role": "user", "content": user_input})
        messages.append({"role": "assistant", "content": full_reply})
        return full_reply

    except Exception as e:
        print(f"\n   ❌ 请求失败：{e}")
        return None

# ========== 主程序 ==========
filename = start_menu()

if filename:
    messages = load_chat(filename)
    print(f"\n📖 已加载对话：{filename} (共{len(messages)-1}条消息)")
    web_mode, budget_limit = choose_options()
    total_input_tokens = total_output_tokens = spent_cost = 0.0
else:
    web_mode, budget_limit = choose_options()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    filename = None

print("=== 你的专属AI助教'小深'已上线 ===")
print("💡 特性：动态情绪感知 | 自我反思纠错 | 严谨排版引擎")
print("输入 'quit' 退出，输入 'stats' 查看用量，输入 'save' 保存对话\n")

while True:
    user_input = input("你：")
    if not user_input.strip(): continue
        
    if user_input.lower() == "quit":
        filename = save_chat(messages, filename)
        print_session_stats()
        print("小深：学习辛苦了，下次见！")
        break
    if user_input.lower() == "stats":
        print_session_stats()
        continue
    if user_input.lower() == "save":
        filename = save_chat(messages, filename)
        continue

    search_summary = None
    if web_mode in ["1", "2"]:
        print("   🔍 正在检索资料...")
        raw_results = google_search_serpapi(user_input)
        if raw_results:
            print("   🗜️ 正在压缩核心知识点...")
            search_summary = compress_search_results(raw_results, "fast" if web_mode == "1" else "full")

    reply = ask_deepseek(user_input, messages, current_model, stream=True, search_summary=search_summary)
    if reply is None: print("   ⚠️ 发生中断，请重新尝试。")

    if budget_limit > 0 and spent_cost >= budget_limit:
        print(f"⚠️ 已超出预算！当前累计花费 ¥{spent_cost:.6f}，预算 ¥{budget_limit:.2f}")
        if input("继续并增加相同额度？(y/n): ").strip().lower() == 'y':
            budget_limit += original_budget
            print(f"💰 预算已提升至 ¥{budget_limit:.2f}\n")
        else:
            filename = save_chat(messages, filename)
            print_session_stats()
            break
