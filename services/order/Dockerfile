FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/order services/order
RUN useradd --uid 10001 --create-home service && mkdir -p /data && chown service:service /data
ENV ORDERS_DB=/data/orders.sqlite3
VOLUME ["/data"]
USER service
EXPOSE 8000
CMD ["uvicorn", "services.order.app:app", "--host", "0.0.0.0", "--port", "8000"]
