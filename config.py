import os
import secrets

class Config:
    # 未設定時，每次啟動產生新的本機祕鑰；正式部署請設定穩定且隨機的 SECRET_KEY。
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_urlsafe(32)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
    MAX_CONTENT_LENGTH = 32 * 1024
    
    # 雲端模型服務：auto（依金鑰開頭判斷）、gemini、anthropic、openai、deepseek、groq、openrouter、xai、mistral、
    # custom（任何 OpenAI 相容服務，需 LLM_BASE_URL）或 builtin（本機回覆）。清單見 engine/providers.py。
    LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "auto")
    # 通用設定：一把金鑰、選填的服務網址與指定模型（未指定時自動挑選最佳可用模型）。
    LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
    LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
    LLM_MODEL = os.environ.get("LLM_MODEL", "")
    # 舊的分家設定仍然有效。
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

    # OpenAI 相容的文字對話模型
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
    OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
    
    # Google Gemini 模型；可用型號與額度以帳號當下顯示為準。
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

    # 一般陪伴 1–4 短句；安全與界線以決策層優先。
    LLM_TEMPERATURE = 0.8
    LLM_TIMEOUT = 25
    # 連線階段上限：網路斷線時幾秒內就改用本機備援，不必等滿 LLM_TIMEOUT。
    LLM_CONNECT_TIMEOUT = float(os.environ.get("LLM_CONNECT_TIMEOUT", "3"))
    # 全站每分鐘最多送出幾次雲端模型請求；超過就改用本機回覆（控制費用，不擋學生）。
    LLM_CALLS_PER_MINUTE = int(os.environ.get("LLM_CALLS_PER_MINUTE", "120"))
    # 自動讀取金鑰可用的模型清單、挑排名最前者，故障時自動換下一個（只在後台顯示）。
    MODEL_AUTO_SELECT = os.environ.get("MODEL_AUTO_SELECT", "true").lower() == "true"
    # low：陪伴短句不需要長時間推理，把 Gemini 的「思考」降到最低以縮短等待；default：用模型原本的設定。
    GEMINI_THINKING = os.environ.get("GEMINI_THINKING", "low").lower()
    # Claude 等會先思考的模型：low（預設，短回覆、等待短）、medium、high、xhigh、max；default 則用模型本身的預設。
    LLM_EFFORT = os.environ.get("LLM_EFFORT", "low").lower()
    # single：一次結構化呼叫同時取得線索與回覆（計畫書 Step 3）；two_stage：先分析、再回覆。
    LLM_CALL_MODE = os.environ.get("LLM_CALL_MODE", "single").lower()
    # 分析＋回覆兩次模型呼叫合計的上限秒數；超過就改用本機備援，不讓學生久等。
    LLM_TURN_BUDGET = float(os.environ.get("LLM_TURN_BUDGET", "30"))
    DIALOGUE_SEMANTIC_ANALYSIS = os.environ.get("DIALOGUE_SEMANTIC_ANALYSIS", "true").lower() == "true"
    # 雲端朗讀語音（engine/tts.py）：有設定金鑰的服務才會出現在學生的聲音選單；只傳 AI 回覆文字，不傳學生訊息。
    TTS_ENABLED = os.environ.get("TTS_ENABLED", "true").lower() == "true"
    AZURE_SPEECH_KEY = os.environ.get("AZURE_SPEECH_KEY", "")
    AZURE_SPEECH_REGION = os.environ.get("AZURE_SPEECH_REGION", "")  # 例如 eastasia、southeastasia
    TTS_OPENAI_MODEL = os.environ.get("TTS_OPENAI_MODEL", "gpt-4o-mini-tts")
    TTS_GEMINI_MODEL = os.environ.get("TTS_GEMINI_MODEL", "")  # 留白時自動找金鑰可用的語音模型
    TTS_CALLS_PER_MINUTE = int(os.environ.get("TTS_CALLS_PER_MINUTE", "60"))  # 全站上限，控制費用
    WORKBENCH_PASSWORD = os.environ.get("WORKBENCH_PASSWORD", "")
    
    DATABASE_PATH = os.environ.get("DATABASE_PATH") or os.path.join(os.path.dirname(__file__), "anla_youth.db")
    DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
    HOST = os.environ.get("HOST", "127.0.0.1")
    # 手機掃碼安裝 PWA 時要開啟的網址（例如 https://anla.example.tw/）；未設定時使用本機區網位址。
    # Render 會自動提供 RENDER_EXTERNAL_URL。
    PUBLIC_URL = os.environ.get("PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL", "")
    # 資安閘道：每段對話每分鐘訊息上限、同一 IP 登入失敗上限（10 分鐘內）、允許跨來源的網址（逗號分隔，預設不開放）。
    CHAT_RATE_LIMIT = int(os.environ.get("CHAT_RATE_LIMIT", "30"))
    LOGIN_MAX_FAILURES = int(os.environ.get("LOGIN_MAX_FAILURES", "5"))
    CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
    # 部署在反向代理（HTTPS 通道、Nginx）後面時設定代理層數，登入鎖定才會依真實來源 IP 計算。
    TRUSTED_PROXY_HOPS = int(os.environ.get("TRUSTED_PROXY_HOPS", "0"))
