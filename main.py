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
import psycopg2

# Import das configurações externas
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
# Inicializa conexão com ToolFront Database (com retries e warm-up)
# -------------------------
MAX_RETRIES = 3
db = None
for attempt in range(1, MAX_RETRIES + 1):
    try:
        logger.info(f"Tentativa {attempt}/{MAX_RETRIES} de conectar ao banco: {DATABASE_URL}")
        db = Database(DATABASE_URL)

        # 🔹 Warm-up: força Ibis a carregar schemas e cache de tabelas
        try:
            tables = db.connection.list_tables()
            logger.info(f"Tabelas visíveis no banco: {tables}")
        except Exception as e:
            logger.warning(f"Erro ao listar tabelas no warm-up: {e}")

        # 🔹 Mostrar search_path
        try:
            search_path = db.connection.raw_sql("SHOW search_path;").fetchall()
            logger.info(f"Search path atual: {search_path}")
        except Exception as e:
            logger.warning(f"Erro ao obter search_path: {e}")

        logger.info("Conexão com o banco criada com sucesso.")
        break
    except Exception as e:
        logger.error(f"Erro ao conectar no banco (tentativa {attempt}): {e}")
        if attempt == MAX_RETRIES:
            raise
        time.sleep(2 * attempt)  # backoff exponencial

# -------------------------
# Limites de proteção
# -------------------------
MAX_CONTEXT_TOKENS = 600
MAX_PROMPT_LENGTH = 200
MAX_RESPONSE_TOKENS = 1000
MAX_CONCURRENT_REQUESTS = 1
semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
ENABLE_TOKEN_CHECK = True

# -------------------------
# Função para contar tokens
# -------------------------
def count_tokens(text: str, model: str = "gpt-4o-mini") -> int:
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(text))

# -------------------------
# Função para truncar contexto
# -------------------------
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

# -------------------------
# Função de validação de queries
# -------------------------
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

# -------------------------
# CORS
# -------------------------
origins = ["http://localhost:5173"] if ENV == "development" else ["https://meu-frontend.com"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
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
    if len(request.pergunta.strip()) == 0:
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
        try:
            loop = asyncio.get_running_loop()
            resposta = await loop.run_in_executor(
                None,
                lambda: db.ask(request.pergunta, model="gpt-4o-mini", context=context_truncado)
            )

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
        except psycopg2.OperationalError as db_err:
            logger.error(f"Erro de conexão com Postgres: {db_err}")
            raise HTTPException(status_code=503, detail="Erro de conexão com o banco.")
        except Exception as e:
            logger.exception("Erro inesperado ao processar pergunta")
            raise HTTPException(status_code=500, detail=str(e))
