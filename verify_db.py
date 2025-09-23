import os
import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv

# -------------------------
# Carregamento do .env
# -------------------------
load_dotenv()
ENV = os.getenv("ENV", "development")

if ENV == "development":
    DATABASE_URL = os.getenv("DATABASE_URL")
else:
    DATABASE_URL = os.getenv("DATABASE_URL_EXTERNAL")

# -------------------------
# Configuração esperada do DB
# -------------------------
EXPECTED_TABLES = {
    "students": [
        "name", "socialName", "preferredName", "ismartEmail", "phoneNumber",
        "gender", "sexualOrientation", "raceEthnicity", "hasDisability", "linkedin",
        # adicione todas as colunas esperadas aqui...
    ],
    # Se houver mais tabelas, coloque aqui
    # "other_table": ["col1", "col2", ...]
}

# -------------------------
# Conexão ao PostgreSQL
# -------------------------
try:
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    print(f"[OK] Conectado ao banco com sucesso: {DATABASE_URL}")
except Exception as e:
    print(f"[ERRO] Falha ao conectar: {e}")
    exit(1)

# -------------------------
# Função para verificar tabelas
# -------------------------
def check_tables():
    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public';")
    existing_tables = [row[0] for row in cur.fetchall()]
    print("\n=== Verificação de Tabelas ===")
    for table in EXPECTED_TABLES.keys():
        if table in existing_tables:
            print(f"[OK] Tabela '{table}' encontrada")
        else:
            print(f"[ERRO] Tabela '{table}' NÃO encontrada")

# -------------------------
# Função para verificar colunas
# -------------------------
def check_columns():
    print("\n=== Verificação de Colunas ===")
    for table, expected_cols in EXPECTED_TABLES.items():
        cur.execute(
            sql.SQL("SELECT column_name FROM information_schema.columns WHERE table_name = %s;"),
            [table]
        )
        existing_cols = [row[0] for row in cur.fetchall()]
        for col in expected_cols:
            if col in existing_cols:
                print(f"[OK] Coluna '{col}' em '{table}' encontrada")
            else:
                print(f"[ERRO] Coluna '{col}' em '{table}' NÃO encontrada")

# -------------------------
# Função para mostrar alguns registros
# -------------------------
def sample_data(limit=5):
    print("\n=== Amostra de dados ===")
    for table in EXPECTED_TABLES.keys():
        try:
            cur.execute(sql.SQL("SELECT * FROM {} LIMIT %s;").format(sql.Identifier(table)), [limit])
            rows = cur.fetchall()
            print(f"\nTabela '{table}' - {len(rows)} registros mostrados:")
            for r in rows:
                print(r)
        except Exception as e:
            print(f"[ERRO] Não foi possível consultar '{table}': {e}")

# -------------------------
# Executa as verificações
# -------------------------
check_tables()
check_columns()
sample_data()

# -------------------------
# Fecha conexão
# -------------------------
cur.close()
conn.close()
