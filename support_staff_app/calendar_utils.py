import datetime
import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/calendar']
TOKEN_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'token.json')
CREDS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'credentials.json')

def get_calendar_service():
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Note: In a headless Streamlit env, this interactive flow might be tricky if token is missing.
            # We assume token.json is present from previous steps.
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, 'w') as token:
            token.write(creds.to_json())

    return build('calendar', 'v3', credentials=creds)

def schedule_1on1(staff_name, staff_email, manager_email, start_dt):
    """
    Schedules a 1on1 meeting for 1 hour.
    """
    service = get_calendar_service()
    
    end_dt = start_dt + datetime.timedelta(hours=1)
    
    event = {
        'summary': f'1on1: {staff_name} / マネージャー',
        'location': 'オンライン / 社内会議室',
        'description': '2週間に1回の定期1on1ミーティング',
        'start': {
            'dateTime': start_dt.isoformat(),
            'timeZone': 'Asia/Tokyo',
        },
        'end': {
            'dateTime': end_dt.isoformat(),
            'timeZone': 'Asia/Tokyo',
        },
        'attendees': [
            {'email': staff_email},
            {'email': manager_email},
        ],
        'reminders': {
            'useDefault': False,
            'overrides': [
                {'method': 'email', 'minutes': 24 * 60},
                {'method': 'popup', 'minutes': 10},
            ],
        },
    }

    event = service.events().insert(calendarId='primary', body=event).execute()
    return event.get('htmlLink')
