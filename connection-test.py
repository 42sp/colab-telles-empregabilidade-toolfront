import psycopg2

DATABASE_URL = "postgres://postgres:93eb9fd3c9c3e4f15821@easypanel.lipe.ph:8021/42sp?sslmode=disable"

try:
    conn = psycopg2.connect(DATABASE_URL)
    print("Conexão bem-sucedida!")
    conn.close()
except Exception as e:
    print("Erro ao conectar:", e)
