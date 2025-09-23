FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt main.py ./

RUN pip install --upgrade pip
RUN pip install uvicorn fastapi git+https://github.com/kruskal-labs/toolfront.git -r requirements.txt

EXPOSE 3000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "3000"]
