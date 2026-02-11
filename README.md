# Crosswalk Safety Dashboard

Frontend-focused dashboard for the IoT-Based Smart School-Zone Crosswalk Alert System.

## Features
- **Live View**: Real-time mock data visualization.
- **Logs**: Event history with filtering and CSV export.
- **Analytics**: Key performance indicators and charts.
- **Reports**: Printable system summary.
- **Settings**: ROI configuration tool (prototype).

## How to Run

1.  **Open Terminal**: Navigate to the project folder:
    ```powershell
    cd c:\Users\Acer\Documents\CAPSTONE\web_dashboard
    ```

2.  **Activate Virtual Environment**:
    ```powershell
    .\venv\Scripts\activate
    ```

3.  **Run Application**:
    ```powershell
    python app.py
    ```

4.  **Access Dashboard**:
    Open your browser and visit:
    [http://127.0.0.1:5000](http://127.0.0.1:5000)

## Configuration
- **Database**: Check `.env` for database settings (defaults to strict mock mode if DB unavailable).
- **Mock Mode**: Can be toggled ON/OFF in the dashboard top bar.
