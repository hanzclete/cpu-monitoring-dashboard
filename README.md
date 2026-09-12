# CPU Monitoring System — Python + PostgreSQL

A simple real-time CPU monitoring dashboard that stores historical hardware metrics in PostgreSQL.

## Features

- Overall CPU utilization
- Per-logical-core CPU usage
- Current CPU frequency
- RAM utilization
- Running process count
- Live CPU/RAM history graph
- PostgreSQL metric history
- REST API endpoints
- Responsive browser dashboard

## Project Structure

```text
cpu_monitoring_postgresql/
├── app.py
├── collector.py
├── db.py
├── init_db.py
├── schema.sql
├── requirements.txt
├── .env.example
├── templates/
│   └── index.html
└── static/
    ├── app.js
    └── style.css
```

## 1. Create PostgreSQL Database

Open **SQL Shell (psql)** and log in as `postgres`.

Run:

```sql
CREATE DATABASE cpu_monitor;
```

Then exit:

```sql
\q
```

The Python app can create the `cpu_monitor` database if it is missing, and it creates the table automatically.

## 2. Open the Project in VS Code

Open the `cpu_monitoring_postgresql` folder.

Open a terminal inside VS Code.

## 3. Create a Virtual Environment

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```

## 4. Install Dependencies

```powershell
pip install -r requirements.txt
```

The project uses the modern `psycopg` PostgreSQL driver so it works with current Python versions.

## 5. Create `.env`

Copy `.env.example` and rename the copy to:

```text
.env
```

Edit the PostgreSQL values:

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=cpu_monitor
DB_USER=postgres
DB_PASSWORD=1234
```

Replace `1234` with your actual PostgreSQL password if different.

## 6. Run the System

```powershell
python app.py
```

Expected output includes:

```text
Database table initialized successfully.
 * Running on http://127.0.0.1:5000
```

Open:

```text
http://localhost:5000
```

## PostgreSQL Table

Table name:

```text
cpu_metrics
```

To view the latest records:

```sql
SELECT *
FROM cpu_metrics
ORDER BY recorded_at DESC
LIMIT 20;
```

## API Endpoints

- `/api/system` — machine information
- `/api/latest` — latest recorded metrics
- `/api/history` — recent CPU/RAM history
- `/api/health` — application health check

## Notes

- Metrics are recorded every 5 seconds by default.
- Change `MONITOR_INTERVAL_SECONDS` in `.env` to change the sampling interval.
- CPU frequency support depends on the operating system and hardware.
- CPU temperature is intentionally not included because Windows does not expose it consistently through `psutil`.
