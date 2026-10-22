import os
import secrets

class Config:
    # 未設定時，每次啟動產生新的本機祕鑰；正式部署請設定穩定且隨機的 SECRET_KEY。
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_urlsafe(32)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
    MAX_CONTENT_LENGTH = 32 * 1024
    
    # 目前啟用的 LLM 供應商: 'gemini', 'openai', 'builtin'
    LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "auto")
    
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
    DIALOGUE_SEMANTIC_ANALYSIS = os.environ.get("DIALOGUE_SEMANTIC_ANALYSIS", "true").lower() == "true"
    WORKBENCH_PASSWORD = os.environ.get("WORKBENCH_PASSWORD", "")
    
    DATABASE_PATH = os.environ.get("DATABASE_PATH") or os.path.join(os.path.dirname(__file__), "anla_youth.db")
    DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
    HOST = os.environ.get("HOST", "127.0.0.1")
