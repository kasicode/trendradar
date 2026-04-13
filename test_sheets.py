import os
import json
import gspread
from google.oauth2.service_account import Credentials

# Load credentials from Railway environment variable
creds_json = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
creds = Credentials.from_service_account_info(
    creds_json,
    scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
)

# Connect to Google Sheets
client = gspread.authorize(creds)
sheet = client.open_by_key("1hriKOJaETWO69ty29cMuR9CPTvMa1X4N").sheet1

# Grab first 3 rows and print them
rows = sheet.get_all_records(head=1)
for row in rows[:3]:
    print(row)

print("✅ Connection works!")
