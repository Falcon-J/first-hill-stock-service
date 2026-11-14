FROM python:3.12-slim
WORKDIR /app
COPY services/stock/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY services/stock /app/services/stock
COPY data/stock_snapshot.csv /app/data/stock_snapshot.csv
RUN useradd --create-home service && mkdir /state && chown service:service /state
USER service
ENV STOCK_STORAGE_PATH=/state/stock.sqlite
EXPOSE 8000
CMD ["uvicorn", "services.stock.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
