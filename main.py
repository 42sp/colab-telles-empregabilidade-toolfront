import logging
import os
import asyncio
import re
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from toolfront import Database
import tiktoken

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
# Inicializa conexão com ToolFront Database
# -------------------------
try:
    db = Database(DATABASE_URL)
    logger.info("Conexão com o banco criada com sucesso.")
except Exception as e:
    logger.error(f"Erro ao conectar no banco: {e}")
    raise

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

    # 1) Só SELECT
    if not q.strip().startswith("select"):
        return False

    # 2) Bloqueio de comandos perigosos
    if any(word in q for word in DANGEROUS_KEYWORDS):
        return False

    # 3) Garantir que só use a tabela certa
    if "public.students" not in q and "students" not in q:
        return False

    # 4) Validar colunas
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
        try:
            loop = asyncio.get_running_loop()
            resposta = await loop.run_in_executor(
                None,
                lambda: db.ask(request.pergunta, model="gpt-4o-mini", context=context_truncado)
            )

            # 🔒 Validação de segurança
            if hasattr(resposta, "sql") and not validate_sql_query(resposta.sql):
                logger.warning(f"Query bloqueada: {resposta.sql}")
                raise HTTPException(status_code=400, detail="Query não permitida por razões de segurança.")

            return {"resposta": str(resposta)}

        except Exception as e:
            logger.exception("Erro ao processar pergunta")
            raise HTTPException(status_code=500, detail=str(e))
