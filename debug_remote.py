import paramiko, sys
sys.stdout.reconfigure(encoding='utf-8')
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('158.247.242.167', username='root', password='[gF6mK.Wg8bjiqY2')

# Upload a test script
sftp = ssh.open_sftp()
with sftp.open('/tmp/test_dashboard.py', 'w') as f:
    f.write('''
import os, django, traceback, sys
sys.stdout.reconfigure(encoding="utf-8")
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
os.chdir("/home/bookmart/bookmart")
sys.path.insert(0, "/home/bookmart/bookmart")
django.setup()

from django.test import RequestFactory
from orders.views import dashboard
from accounts.models import User

try:
    u = User.objects.filter(role="admin").first()
    print("Admin user:", u)
    factory = RequestFactory()
    req = factory.get("/dashboard/")
    req.user = u
    from django.contrib.sessions.backends.db import SessionStore
    req.session = SessionStore()
    from django.contrib.messages.storage.fallback import FallbackStorage
    setattr(req, '_messages', FallbackStorage(req))
    resp = dashboard(req)
    print("Status:", resp.status_code)
except Exception as e:
    traceback.print_exc()
''')
sftp.close()

stdin, stdout, stderr = ssh.exec_command('cd /home/bookmart/bookmart && source venv/bin/activate && python /tmp/test_dashboard.py 2>&1')
print(stdout.read().decode('utf-8', errors='replace'))
print('STDERR:', stderr.read().decode('utf-8', errors='replace'))
ssh.close()
