import logging
import os
import asyncio
import re
import time
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from toolfront import Database
from pydantic_ai.exceptions import ModelRetry
import tiktoken
import psycopg
from urllib.parse import urlparse, parse_qs
from psycopg_pool import ConnectionPool

# -------------------------
# Configurações externas
# -------------------------
from config.security import CONTEXT, ALLOWED_COLUMNS, DANGEROUS_KEYWORDS

# -------------------------
# Carregamento de .env
# -------------------------
load_dotenv()
ENV = os.getenv("ENV", "development")
DATABASE_URL = os.getenv("DATABASE_URL")

# -------------------------
# Logging
# -------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("toolfront_api")

# -------------------------
# Pool de conexões com psycopg3
# -------------------------
DB_POOL_MIN = 1
DB_POOL_MAX = 5
DB_POOL_MAX_LIFETIME = 900  # 15 minutos
db_pool: ConnectionPool | None = None
db: Database | None = None

def parse_database_url(url: str):
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    return {
        "user": parsed.username,
        "password": parsed.password,
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "dbname": parsed.path.lstrip("/"),
        "sslmode": qs.get("sslmode", ["disable"])[0]
    }

def init_db_pool():
    """Inicializa pool e objeto Database"""
    global db_pool, db
    if db_pool:
        db_pool.close()
    
    db_pool = ConnectionPool(
        conninfo=DATABASE_URL,
        min_size=DB_POOL_MIN,
        max_size=DB_POOL_MAX
    )

    # Configura search_path nas conexões iniciais
    with db_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SET search_path TO public;")

    db = Database(DATABASE_URL)
    logger.info("Pool de conexões e Database inicializados.")

def get_conn_from_pool():
    """Retorna um context manager de conexão válida do pool"""
    global db_pool
    if not db_pool:
        init_db_pool()
    
    for _ in range(3):
        try:
            return db_pool.connection()  # <-- retorna o context manager corretamente
        except Exception as e:
            logger.warning(f"Conexão inválida: {e}. Reinicializando pool...")
            init_db_pool()
    raise Exception("Não foi possível obter conexão válida")

async def keep_alive():
    """Executa SELECT 1 periodicamente para evitar timeout"""
    while True:
        try:
            with get_conn_from_pool() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
        except Exception as e:
            logger.warning(f"Keep-alive falhou, reiniciando pool: {e}")
            init_db_pool()
        await asyncio.sleep(60)

# Inicializa pool no startup
init_db_pool()

# -------------------------
# Limites de proteção
# -------------------------
MAX_CONTEXT_TOKENS = 800
MAX_PROMPT_LENGTH = 400
MAX_RESPONSE_TOKENS = 2000
MAX_CONCURRENT_REQUESTS = 1
semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
ENABLE_TOKEN_CHECK = True

# -------------------------
# Funções utilitárias
# -------------------------
def count_tokens(text: str, model: str = "gpt-4o-mini") -> int:
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(text))

def truncate_context(ctx: str) -> str:
    lines = ctx.strip().split("\n")
    truncated = []
    token_count = 0
    for line in reversed(lines):
        token_count += len(tiktoken.get_encoding("cl100k_base").encode(line))
        if token_count > MAX_CONTEXT_TOKENS:
            break
        truncated.insert(0, line)
    return "\n".join(truncated)

def validate_sql_query(query: str) -> bool:
    q = query.lower()
    if not q.strip().startswith("select"):
        return False
    if any(word in q for word in DANGEROUS_KEYWORDS):
        return False
    if "public.students" not in q and "students" not in q:
        return False
    match = re.search(r"select\s+(.*?)\s+from", q, re.DOTALL)
    if match:
        cols = match.group(1).replace(" ", "").split(",")
        for col in cols:
            if col != "*" and col not in ALLOWED_COLUMNS:
                return False
    return True

# -------------------------
# Inicializa FastAPI
# -------------------------
app = FastAPI(title="ToolFront Chat API")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(keep_alive())
    logger.info("Keep-alive iniciado para manter conexões ativas.")

# -------------------------
# CORS
# -------------------------
origins = (
    ["http://localhost:5173"]
    if ENV == "development"
    else [
        "https://colab-telles-empregabilidade-frontend.onrender.com",
        "https://temp-empregabilidade-toolfront.eorpdr.easypanel.host"
    ]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------
# Modelo de request
# -------------------------
class AskRequest(BaseModel):
    pergunta: str

# -------------------------
# Endpoint /ask
# -------------------------
@app.post("/ask")
async def ask_question(request: AskRequest):
    if not request.pergunta.strip():
        raise HTTPException(status_code=400, detail="Pergunta não pode ser vazia.")
    if len(request.pergunta) > MAX_PROMPT_LENGTH:
        raise HTTPException(status_code=400, detail=f"Pergunta muito longa ({len(request.pergunta)} caracteres).")

    context_truncado = truncate_context(CONTEXT)

    if ENABLE_TOKEN_CHECK:
        context_tokens = count_tokens(context_truncado)
        pergunta_tokens = count_tokens(request.pergunta)
        total_tokens = context_tokens + pergunta_tokens + MAX_RESPONSE_TOKENS
        logger.info(f"Tokens usados -> Contexto: {context_tokens}, Pergunta: {pergunta_tokens}, Máx Resposta: {MAX_RESPONSE_TOKENS}, Total: {total_tokens}")
        if total_tokens > 128000:
            raise HTTPException(status_code=400, detail=f"Requisição excede limite de tokens ({total_tokens} > 128000).")

    async with semaphore:
        start_time = time.time()
        loop = asyncio.get_running_loop()

        def ask_with_reconnect():
            global db
            for attempt in range(3):
                try:
                    return db.ask(request.pergunta, model="gpt-4o-mini", context=context_truncado)
                except (psycopg.OperationalError, psycopg.InterfaceError) as e:
                    logger.warning(f"Conexão perdida (tentativa {attempt+1}): {e}. Reinicializando db...")
                    init_db_pool()
                    time.sleep(1)
            raise HTTPException(status_code=503, detail="Falha ao conectar ao banco após múltiplas tentativas.")

        try:
            resposta = await loop.run_in_executor(None, ask_with_reconnect)

            if hasattr(resposta, "sql"):
                logger.info(f"[SQL Gerada] {resposta.sql}")
                if not validate_sql_query(resposta.sql):
                    logger.warning(f"Query bloqueada: {resposta.sql}")
                    raise HTTPException(status_code=400, detail="Query não permitida por razões de segurança.")

            elapsed = time.time() - start_time
            logger.info(f"Pergunta processada em {elapsed:.2f}s")
            return {"resposta": str(resposta)}

        except ModelRetry as mr:
            logger.warning(f"Retry do modelo: {mr}")
            raise HTTPException(status_code=503, detail="O modelo pediu retry. Tente novamente.")
        except Exception as e:
            logger.exception("Erro inesperado ao processar pergunta")
            raise HTTPException(status_code=500, detail=str(e))


@app.post("/reconnect-db")
async def reconnect_db():
    """Força reinicialização do pool de conexões e do objeto Database"""
    try:
        with get_conn_from_pool() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
        return {"success": True, "db_connected": True}
    except Exception as e:
        logger.exception("Falha ao reconectar ao DB")
        return {"success": False, "db_connected": False, "error": str(e)}


@app.get("/health")
async def health_check():
    try:
        with get_conn_from_pool() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
        return {"status": "connected"}
    except Exception:
        return {"status": "disconnected"}
