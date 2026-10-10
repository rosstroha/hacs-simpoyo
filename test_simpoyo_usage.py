import contextlib
from datetime import date
from email.message import EmailMessage
import io
import json
import os
import sys
import threading
import tempfile
import time
import unittest
from http.cookiejar import CookieJar, MozillaCookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs
from urllib.request import HTTPCookieProcessor, build_opener

import simpoyo_usage
from simpoyo_usage import load_usage, login


HTML = '''<div class="customer-plan">ICCID: 1234567890 ICCID Name: Travel
<div class="plan-item">US <canvas class="usage-pie" data-usage="37.5"></canvas>
<span>Data Left</span><span>2.5 GB</span><span>Data Used</span><span>1.5 GB</span>
<div>Total Data</div><div>4 GB</div><div>Plan Valid Until</div><div>30/09/2026</div>
</div></div>'''


class Site(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def reply(self, status, body, cookie=None):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/my-account/':
            logged_in = 'wordpress_logged_in_test=valid' in self.headers.get('Cookie', '')
            body = b'<body class="logged-in woocommerce-account"></body>' if logged_in else b'<body class="woocommerce-account"></body>'
            self.reply(200, body)
            return
        if self.path != '/':
            self.reply(404, b'{}')
            return
        self.reply(200, b'<input name="woocommerce-login-nonce" value="fresh-nonce">')

    def do_POST(self):
        if self.path != '/wp-admin/admin-ajax.php':
            self.reply(404, b'{}')
            return
        form = {key: values[0] for key, values in parse_qs(
            self.rfile.read(int(self.headers['Content-Length'])).decode(),
            keep_blank_values=True,
        ).items()}
        action = form.get('action')
        if action == 'ajax_login' and form == {
            'action': 'ajax_login', 'username': 'user@example.com',
            'woocommerce-login-nonce': 'fresh-nonce', '_wp_http_referer': '/',
        }:
            self.server.code_sent = True
            self.reply(200, b'{"success":true,"email":"user@example.com"}', 'woo=one; Path=/')
        elif action == 'ajax_login_otp' and all([
            self.headers.get('Cookie') == 'woo=one',
            form.get('email') == 'user@example.com',
            form.get('check_session_set') == '', form.get('redirect') == '',
            ''.join(form.get(f'digit-{i}', '') for i in range(1, 7)) == '123456',
        ]):
            self.reply(200, b'{"success":true,"returnUrl":"/my-account/"}', 'wordpress_logged_in_test=valid; Path=/')
        elif action == 'load_customer_plans' and 'wordpress_logged_in_test=valid' in self.headers.get('Cookie', ''):
            self.reply(200, json.dumps({'ok': True, 'html': HTML}).encode())
        elif action == 'load_customer_plans':
            self.reply(400, b'0')
        else:
            self.reply(400, b'{"success":false}')


class UsageTest(unittest.TestCase):
    def test_sensor_payload_sums_current_usage_and_splits_plan_attributes(self):
        def plan(name, left, used, total, until):
            return {
                'iccid': '1234567890', 'name': name, 'plan': 'Travel',
                'data_left': left, 'data_used': used,
                'total_data': total, 'valid_until': until,
            }

        result = simpoyo_usage.sensor_payload({
            'status': 'ok', 'checked_at': '2026-09-29T12:00:00Z', 'error': None,
            'plans': [
                plan('Available', '0.42GB', '7.58GB', '8GB', '29/09/2026'),
                plan('Depleted', '0GB', '8GB', '8GB', '29/09/2026'),
                plan('Small', '512MB', '512MB', '1GB', '30/09/2026'),
                plan('Expired', '1GB', '7GB', '8GB', '28/09/2026'),
            ],
        }, date(2026, 9, 29))
        self.assertEqual(result['data_used_gb'], 16.08)
        self.assertEqual(result['flat_attributes']['active_plan_count'], 3)
        self.assertEqual(result['flat_attributes']['plan_2_name'], 'Depleted')
        self.assertEqual(result['flat_attributes']['plan_2_data_left'], '0GB')
        self.assertEqual(result['flat_attributes']['plan_3_data_used'], '512MB')
        self.assertNotIn('plan_4_name', result['flat_attributes'])
        self.assertEqual(result['flat_attributes']['status'], 'ok')
        self.assertEqual(result['plans'][3]['name'], 'Expired')

    def test_usage_http_400_with_logged_in_session_does_not_request_code(self):
        class BrokenUsageSite(Site):
            def do_POST(self):
                if self.path == '/wp-admin/admin-ajax.php' and self.server.break_usage:
                    self.rfile.read(int(self.headers['Content-Length']))
                    self.reply(400, b'0')
                else:
                    super().do_POST()

        server = ThreadingHTTPServer(('127.0.0.1', 0), BrokenUsageSite)
        server.break_usage = False
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'config.json'
            config.write_text(json.dumps({
                'email': 'user@example.com',
                'gmail_app_password': 'abcdefghijklmnop',
            }))
            cookies = MozillaCookieJar(str(Path(directory) / 'cookies.txt'))
            login(build_opener(HTTPCookieProcessor(cookies)), 'user@example.com', lambda: '123456', base)
            cookies.save(ignore_discard=True)
            server.break_usage = True
            with patch.object(simpoyo_usage, 'BASE', base), patch.object(simpoyo_usage, 'CONFIG_FILE', config), patch.object(simpoyo_usage.imaplib, 'IMAP4_SSL', side_effect=AssertionError('unexpected login code')):
                with self.assertRaises(HTTPError) as caught:
                    simpoyo_usage.fetch_usage()
            self.assertEqual(caught.exception.code, 400)

    def test_unrelated_http_400_while_logged_out_does_not_request_code(self):
        class UnrelatedUsageSite(Site):
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.reply(400, b'{"success":false}')

        server = ThreadingHTTPServer(('127.0.0.1', 0), UnrelatedUsageSite)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'config.json'
            config.write_text(json.dumps({
                'email': 'user@example.com',
                'gmail_app_password': 'abcdefghijklmnop',
            }))
            base = f'http://127.0.0.1:{server.server_port}'
            with patch.object(simpoyo_usage, 'BASE', base), patch.object(simpoyo_usage, 'CONFIG_FILE', config), patch.object(simpoyo_usage.imaplib, 'IMAP4_SSL', side_effect=AssertionError('unexpected login code')):
                with self.assertRaises(HTTPError) as caught:
                    simpoyo_usage.fetch_usage()
            self.assertEqual(caught.exception.code, 400)

    def test_email_code_creates_reusable_session_and_returns_usage(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Site)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        cookies = CookieJar()
        opener = build_opener(HTTPCookieProcessor(cookies))
        base = f'http://127.0.0.1:{server.server_port}'
        def emailed_code():
            self.assertTrue(server.code_sent, 'code was requested before prompting')
            return '123456'

        login(opener, 'user@example.com', emailed_code, base)
        expected = [{
            'iccid': '1234567890', 'name': 'Travel', 'plan': 'US',
            'data_left': '2.5 GB', 'data_used': '1.5 GB',
            'total_data': '4 GB', 'valid_until': '30/09/2026',
        }]
        self.assertEqual(load_usage(opener, base), expected)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cookies'
            saved = MozillaCookieJar(str(path))
            for cookie in cookies:
                saved.set_cookie(cookie)
            saved.save(ignore_discard=True)
            os.chmod(path, 0o644)
            output = io.StringIO()
            with patch.object(simpoyo_usage, 'COOKIE_FILE', path), patch.object(simpoyo_usage, 'BASE', base), contextlib.redirect_stdout(output):
                simpoyo_usage.main()
            self.assertEqual(json.loads(output.getvalue()), expected)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_new_simpoyo_email_supplies_code_without_using_older_mail(self):
        def message(sender, code):
            mail = EmailMessage()
            mail['Received'] = 'from mail.example by mx.google.com with ESMTPS'
            mail['Authentication-Results'] = 'mx.google.com; dmarc=pass header.from=voyeglobal.com'
            mail['From'] = sender
            mail['Subject'] = 'Voye OTP (One Time Password)'
            mail.set_content('Please use the following OTP (One Time Password) below:')
            mail.add_alternative(f'<p>Please use the following OTP (One Time Password) below:</p><strong>{code}</strong>', subtype='html')
            return mail.as_bytes()

        class Mailbox:
            def __init__(self):
                self.messages = {5: message('support@voyeglobal.com', '111111')}
                self.refreshed = False

            def noop(self):
                self.refreshed = True
                return 'OK', [b'']

            def uid(self, action, *args):
                if action == 'SEARCH':
                    if args != (None, 'ALL') or not self.refreshed:
                        return 'OK', [b'5']
                    return 'OK', [b' '.join(str(uid).encode() for uid in self.messages)]
                if action == 'FETCH':
                    return 'OK', [(b'BODY[]', self.messages[int(args[0])])]
                raise AssertionError(action)

        mailbox = Mailbox()
        baseline = simpoyo_usage.latest_uid(mailbox)
        mailbox.messages[6] = message('stranger@example.com', '999999')
        mailbox.messages[7] = message('glinet <support@voyeglobal.com>', '654321')
        self.assertEqual(simpoyo_usage.wait_for_code(mailbox, baseline, timeout=1), '654321')

    def test_gmail_configuration_renews_expired_site_session_without_prompt(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Site)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        mail = EmailMessage()
        mail['Received'] = 'from mail.example by mx.google.com with ESMTPS'
        mail['Authentication-Results'] = 'mx.google.com; dmarc=pass header.from=voyeglobal.com'
        mail['From'] = 'glinet <support@voyeglobal.com>'
        mail['Subject'] = 'Voye OTP (One Time Password)'
        mail.set_content('Please use the following OTP (One Time Password) below:')
        mail.add_alternative('<p>Please use the following OTP (One Time Password) below:</p><strong>123456</strong>', subtype='html')

        class Mailbox:
            def login(self, user, password):
                if (user, password) != ('mailbox@example.com', 'abcdefghijklmnop'):
                    raise AssertionError('unexpected Gmail credentials')

            def noop(self):
                return 'OK', [b'']

            def select(self, folder, readonly=False):
                if (folder, readonly) != ('INBOX', True):
                    raise AssertionError('unexpected mailbox selection')
                return 'OK', [b'1']

            def uid(self, action, *args):
                if action == 'SEARCH':
                    return 'OK', [b'5 6' if getattr(server, 'code_sent', False) else b'5']
                if action == 'FETCH' and args[0] == '6':
                    return 'OK', [(b'BODY[]', mail.as_bytes())]
                raise AssertionError('older email was fetched')

            def logout(self):
                pass

        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'config.json'
            config.write_text(json.dumps({
                'email': 'user@example.com',
                'gmail_email': 'mailbox@example.com',
                'gmail_app_password': 'abcdefghijklmnop',
            }))
            output = io.StringIO()
            base = f'http://127.0.0.1:{server.server_port}'
            with patch.object(simpoyo_usage, 'BASE', base), patch.object(simpoyo_usage, 'CONFIG_FILE', config), patch.object(simpoyo_usage.imaplib, 'IMAP4_SSL', return_value=Mailbox()), contextlib.redirect_stdout(output):
                simpoyo_usage.main()
            self.assertEqual(json.loads(output.getvalue())[0]['data_left'], '2.5 GB')
            self.assertEqual((Path(directory) / 'cookies.txt').stat().st_mode & 0o777, 0o600)
            ha_output = io.StringIO()
            with patch.object(simpoyo_usage, 'BASE', base), patch.object(simpoyo_usage, 'CONFIG_FILE', config), patch.object(sys, 'argv', ['simpoyo_usage.py', '--ha']), contextlib.redirect_stdout(ha_output):
                simpoyo_usage.main()
            payload = json.loads(ha_output.getvalue())
            self.assertEqual(payload['plans'][0]['data_left'], '2.5 GB')
            self.assertIn('checked_at', payload)

            worker_output = io.StringIO()
            with patch.object(simpoyo_usage, 'BASE', base), patch.object(simpoyo_usage, 'CONFIG_FILE', config), patch.object(sys, 'argv', ['simpoyo_usage.py', '--ha-worker']), contextlib.redirect_stdout(worker_output):
                simpoyo_usage.main()
            self.assertEqual(worker_output.getvalue(), '')
            cache = json.loads((Path(directory) / 'usage-cache.json').read_text())
            self.assertEqual(cache['status'], 'ok')
            self.assertEqual(cache['plans'][0]['data_left'], '2.5 GB')

    def test_home_assistant_poll_returns_pending_without_waiting_for_network(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'config.json'
            output = io.StringIO()
            start = time.monotonic()
            with patch.object(simpoyo_usage, 'CONFIG_FILE', config), patch.object(sys, 'argv', ['simpoyo_usage.py', '--ha-poll']), patch.object(simpoyo_usage.subprocess, 'Popen') as spawned, contextlib.redirect_stdout(output):
                simpoyo_usage.main()
            self.assertLess(time.monotonic() - start, 1)
            self.assertEqual(json.loads(output.getvalue()), {
                'status': 'pending', 'error': None, 'checked_at': None, 'plans': [],
                'data_used_gb': 0,
                'flat_attributes': {
                    'status': 'pending', 'error': None, 'checked_at': None,
                    'active_plan_count': 0,
                },
            })
            self.assertTrue(spawned.called)

    def test_poll_starts_worker_even_when_cached_usage_cannot_be_parsed(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'config.json'
            cached = {
                'status': 'ok', 'error': None, 'checked_at': '2026-09-29T12:00:00Z',
                'plans': [{
                    'valid_until': '30/09/2099', 'data_used': 'unknown',
                    'data_left': '1GB', 'total_data': '8GB',
                }],
            }
            with patch.object(simpoyo_usage, 'CONFIG_FILE', config), patch.object(simpoyo_usage, 'cached_result', return_value=cached), patch.object(simpoyo_usage.subprocess, 'Popen') as spawned:
                with self.assertRaises(ValueError):
                    simpoyo_usage.poll_cache()
            self.assertTrue(spawned.called)


if __name__ == '__main__':
    unittest.main()
